"""
Face enrollment CLI — builds the local (encrypted, gitignored) embedding store.

    python -m jetson.enroll --name Win --image photo1.jpg photo2.jpg
    python -m jetson.enroll --name Win --camera            # grab from the RTSP cam
    python -m jetson.enroll --list
    python -m jetson.enroll --remove Win

Use 3-5 photos per person (different angles/lighting) for solid recognition.
"""

import argparse
import logging
import sys
import time
from pathlib import Path

import cv2
import yaml

from .embedding_store import EmbeddingStore

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("jetson.enroll")

DEFAULT_CONFIG = Path(__file__).parent / "config.yaml"


def _load_face_app(cfg: dict):
    from insightface.app import FaceAnalysis

    face_cfg = cfg.get("face", {})
    app = FaceAnalysis(
        name=face_cfg.get("model_pack", "buffalo_l"),
        providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
    )
    det = int(face_cfg.get("det_size", 640))
    app.prepare(ctx_id=0, det_size=(det, det))
    return app


def _largest_face(app, image):
    faces = app.get(image)
    if not faces:
        return None
    return max(
        faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1])
    )


def enroll_images(store, app, name, paths):
    added = 0
    for p in paths:
        image = cv2.imread(str(p))
        if image is None:
            logger.error("Could not read image: %s", p)
            continue
        face = _largest_face(app, image)
        if face is None:
            logger.error("No face found in %s", p)
            continue
        store.add(name, face.normed_embedding)
        added += 1
    return added


def enroll_camera(store, app, name, cfg, samples=5):
    from .gst_camera import RtspCamera

    cam_cfg = cfg.get("camera", {})
    camera = RtspCamera(
        cam_cfg.get("rtsp_url", ""),
        codec=cam_cfg.get("codec", "h264"),
        latency_ms=int(cam_cfg.get("latency_ms", 200)),
    )
    camera.start()
    logger.info("Look at the camera — grabbing %d samples...", samples)
    added = 0
    last_frame_id = -1
    deadline = time.monotonic() + 60
    try:
        while added < samples and time.monotonic() < deadline:
            latest = camera.get_latest()
            if latest is None or latest[0] == last_frame_id:
                time.sleep(0.1)
                continue
            last_frame_id, image = latest
            face = _largest_face(app, image)
            if face is None:
                continue
            store.add(name, face.normed_embedding)
            added += 1
            logger.info("Captured sample %d/%d", added, samples)
            time.sleep(1.0)  # space samples out for pose variety
    finally:
        camera.stop()
    return added


def main() -> int:
    parser = argparse.ArgumentParser(description="Enroll faces for ULTRON VISION")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--name", help="Identity to enroll (as Mother will speak it)")
    parser.add_argument("--image", nargs="+", help="Photo file(s) to enroll from")
    parser.add_argument("--camera", action="store_true", help="Enroll from the RTSP camera")
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--list", action="store_true", help="List enrolled identities")
    parser.add_argument("--remove", metavar="NAME", help="Remove an identity")
    args = parser.parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    store = EmbeddingStore(cfg.get("face", {}).get("store_dir", "data/faces"))

    if args.list:
        counts = store.sample_counts()
        if not counts:
            print("No identities enrolled.")
        for name, n in sorted(counts.items()):
            print("  {}  ({} samples)".format(name, n))
        return 0

    if args.remove:
        ok = store.remove(args.remove)
        print("Removed." if ok else "No such identity: {}".format(args.remove))
        return 0 if ok else 1

    if not args.name or not (args.image or args.camera):
        parser.error("need --name plus --image or --camera (or use --list / --remove)")

    app = _load_face_app(cfg)
    if args.image:
        added = enroll_images(store, app, args.name, args.image)
    else:
        added = enroll_camera(store, app, args.name, cfg, samples=args.samples)

    if added == 0:
        logger.error("Nothing enrolled for %s", args.name)
        return 1
    logger.info("Enrolled %d sample(s) for %s", added, args.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
