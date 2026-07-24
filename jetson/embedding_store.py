"""
Local face-embedding store — biometric data on real people.

- Lives under data/faces/ which is gitignored; NEVER commit it.
- Encrypted at rest with Fernet (AES128-CBC + HMAC). The key sits next to the
  store with 0600 perms — this protects against casual copying/backups of the
  data file, not against an attacker with root on the Jetson. Move the key to
  a different volume (or a TPM-backed secret) for stronger guarantees.
"""

import json
import logging
import os
import stat
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

try:
    from cryptography.fernet import Fernet
    CRYPTO_AVAILABLE = True
except ImportError:
    Fernet = None
    CRYPTO_AVAILABLE = False

logger = logging.getLogger(__name__)

STORE_FILE = "embeddings.enc"
PLAIN_FILE = "embeddings.json"  # fallback only, if cryptography is missing
KEY_FILE = ".embed_key"


class EmbeddingStore:
    """Named ArcFace embeddings with cosine-similarity matching."""

    def __init__(self, store_dir: str = "data/faces"):
        self.dir = Path(store_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._faces: Dict[str, List[List[float]]] = {}
        # Flat matching caches
        self._matrix: Optional[np.ndarray] = None
        self._names: List[str] = []

        if not CRYPTO_AVAILABLE:
            logger.warning(
                "cryptography not installed — face embeddings will be stored "
                "in PLAINTEXT at %s. Install 'cryptography' to encrypt at rest.",
                self.dir / PLAIN_FILE,
            )
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _key(self) -> bytes:
        key_path = self.dir / KEY_FILE
        if key_path.exists():
            return key_path.read_bytes().strip()
        key = Fernet.generate_key()
        key_path.write_bytes(key)
        try:
            os.chmod(str(key_path), stat.S_IRUSR | stat.S_IWUSR)  # 0600
        except OSError:
            pass  # non-POSIX filesystem
        logger.info("Generated new embedding encryption key at %s", key_path)
        return key

    def _load(self):
        enc_path = self.dir / STORE_FILE
        plain_path = self.dir / PLAIN_FILE
        try:
            if CRYPTO_AVAILABLE and enc_path.exists():
                raw = Fernet(self._key()).decrypt(enc_path.read_bytes())
                self._faces = json.loads(raw.decode("utf-8"))
            elif plain_path.exists():
                self._faces = json.loads(plain_path.read_text("utf-8"))
            else:
                self._faces = {}
        except Exception as e:
            logger.error("Failed to load embedding store: %s", e)
            self._faces = {}
        self._rebuild()
        logger.info(
            "Embedding store loaded: %d identities (%s)",
            len(self._faces),
            "encrypted" if CRYPTO_AVAILABLE else "PLAINTEXT",
        )

    def _save(self):
        blob = json.dumps(self._faces).encode("utf-8")
        if CRYPTO_AVAILABLE:
            path = self.dir / STORE_FILE
            path.write_bytes(Fernet(self._key()).encrypt(blob))
        else:
            path = self.dir / PLAIN_FILE
            path.write_bytes(blob)
        try:
            os.chmod(str(path), stat.S_IRUSR | stat.S_IWUSR)  # 0600
        except OSError:
            pass

    def _rebuild(self):
        rows, names = [], []
        for name, embs in self._faces.items():
            for e in embs:
                rows.append(e)
                names.append(name)
        self._names = names
        if rows:
            m = np.asarray(rows, dtype=np.float32)
            # Normalize so matching is a plain dot product (cosine similarity)
            norms = np.linalg.norm(m, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            self._matrix = m / norms
        else:
            self._matrix = None

    # ------------------------------------------------------------------
    # API
    # ------------------------------------------------------------------

    def add(self, name: str, embedding: np.ndarray):
        with self._lock:
            self._faces.setdefault(name, []).append(
                np.asarray(embedding, dtype=np.float32).ravel().tolist()
            )
            self._rebuild()
            self._save()
        logger.info(
            "Enrolled embedding for '%s' (%d samples)", name, len(self._faces[name])
        )

    def remove(self, name: str) -> bool:
        with self._lock:
            if name not in self._faces:
                return False
            del self._faces[name]
            self._rebuild()
            self._save()
        logger.info("Removed identity '%s'", name)
        return True

    def names(self) -> List[str]:
        return list(self._faces.keys())

    def sample_counts(self) -> Dict[str, int]:
        return {n: len(e) for n, e in self._faces.items()}

    def best_match(self, embedding: np.ndarray) -> Tuple[Optional[str], float]:
        """Return (name, cosine_similarity) of the closest enrolled identity,
        or (None, 0.0) if nothing is enrolled."""
        with self._lock:
            if self._matrix is None:
                return None, 0.0
            e = np.asarray(embedding, dtype=np.float32).ravel()
            norm = np.linalg.norm(e)
            if norm == 0:
                return None, 0.0
            sims = self._matrix @ (e / norm)
            idx = int(np.argmax(sims))
            return self._names[idx], float(sims[idx])
