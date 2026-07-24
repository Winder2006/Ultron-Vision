"""
Face detection + recognition via InsightFace (RetinaFace det, ArcFace rec),
running on the Jetson GPU through onnxruntime's CUDAExecutionProvider.

Confidence calibration
----------------------
Mother phrases identity by confidence band:
    > 0.85      states the name plainly
    0.60-0.85   "name (uncertain)"
    < 0.60      "an unidentified person"

ArcFace cosine similarity is mapped linearly onto those bands using two
anchors from config (defaults: sim 0.35 -> conf 0.60, sim 0.55 -> conf 0.85).
Anything that calibrates below 0.60 is sent as name "unknown".
"""

import logging
from typing import List, Tuple

import numpy as np

from .embedding_store import EmbeddingStore

logger = logging.getLogger(__name__)


class FaceEngine:
    def __init__(
        self,
        store: EmbeddingStore,
        model_pack: str = "buffalo_l",
        det_size: int = 640,
        min_face_size: int = 40,
        sim_at_conf_060: float = 0.35,
        sim_at_conf_085: float = 0.55,
    ):
        self.store = store
        self.min_face_size = min_face_size
        self.sim60 = sim_at_conf_060
        self.sim85 = sim_at_conf_085

        from insightface.app import FaceAnalysis  # heavy import, keep lazy

        self.app = FaceAnalysis(
            name=model_pack,
            providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
        )
        self.app.prepare(ctx_id=0, det_size=(det_size, det_size))
        active = self.app.models["recognition"].session.get_providers()[0]
        if active != "CUDAExecutionProvider":
            logger.warning(
                "InsightFace running on %s — install the Jetson onnxruntime-gpu "
                "wheel for GPU inference (see jetson/README.md)", active
            )
        logger.info("FaceEngine ready (pack=%s, provider=%s)", model_pack, active)

    def calibrate(self, sim: float) -> float:
        """Cosine similarity -> Mother confidence, via the two config anchors."""
        span = self.sim85 - self.sim60
        if span <= 0:
            return 0.0
        conf = 0.60 + (sim - self.sim60) * (0.85 - 0.60) / span
        return max(0.0, min(0.99, conf))

    def identify_frame(self, frame_bgr: np.ndarray) -> List[Tuple[str, float]]:
        """Detect + recognize every face in the frame.

        Returns [(name, confidence)] with name "unknown" for faces that don't
        calibrate to >= 0.60 against any enrolled identity.
        """
        results: List[Tuple[str, float]] = []
        faces = self.app.get(frame_bgr)
        for face in faces:
            x1, y1, x2, y2 = face.bbox
            if min(x2 - x1, y2 - y1) < self.min_face_size:
                continue
            name, sim = self.store.best_match(face.normed_embedding)
            conf = self.calibrate(sim)
            if name is None or conf < 0.60:
                results.append(("unknown", conf))
            else:
                results.append((name, conf))
        return results
