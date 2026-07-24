"""
ULTRON VISION — Jetson MQTT vision service (main entry point).

    python -m jetson.vision_service [--config jetson/config.yaml]

Pipeline: Tapo RTSP -> NVDEC decode -> InsightFace (faces) + YOLO (objects)
-> presence trackers -> MQTT events to Mother. Events only; frames never
leave the Jetson.
"""

import argparse
import logging
import signal
import sys
import time
from pathlib import Path

import yaml

from .embedding_store import EmbeddingStore
from .face_engine import FaceEngine
from .gst_camera import RtspCamera
from .mqtt_publisher import VisionPublisher
from .object_engine import ObjectEngine
from .presence import FacePresence, ObjectPresence, OccupancyTracker

logger = logging.getLogger("jetson.vision_service")

DEFAULT_CONFIG = Path(__file__).parent / "config.yaml"


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def main() -> int:
    parser = argparse.ArgumentParser(description="ULTRON VISION Jetson MQTT service")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )

    cfg = load_config(args.config)
    cam_cfg = cfg.get("camera", {})
    mqtt_cfg = cfg.get("mqtt", {})
    face_cfg = cfg.get("face", {})
    obj_cfg = cfg.get("objects", {})
    occ_cfg = cfg.get("occupancy", {})

    rtsp_url = cam_cfg.get("rtsp_url", "")
    if "CAMERA_USER" in rtsp_url or not rtsp_url:
        logger.error(
            "Set camera.rtsp_url in %s (create a Camera Account in the Tapo "
            "app: Camera Settings -> Advanced Settings -> Camera Account).",
            args.config,
        )
        return 1

    # --- MQTT ---------------------------------------------------------
    publisher = VisionPublisher(
        host=mqtt_cfg.get("host", "127.0.0.1"),
        port=int(mqtt_cfg.get("port", 1883)),
        client_id=mqtt_cfg.get("client_id"),
        username=mqtt_cfg.get("username"),
        password=mqtt_cfg.get("password"),
    )
    publisher.connect()

    # --- Engines ------------------------------------------------------
    store = EmbeddingStore(face_cfg.get("store_dir", "data/faces"))
    if not store.names():
        logger.warning(
            "No faces enrolled — everyone will be published as \"unknown\". "
            "Enroll with: python -m jetson.enroll --name Win --image photo.jpg"
        )

    face_engine = None
    try:
        face_engine = FaceEngine(
            store,
            model_pack=face_cfg.get("model_pack", "buffalo_l"),
            det_size=int(face_cfg.get("det_size", 640)),
            min_face_size=int(face_cfg.get("min_face_size", 40)),
            sim_at_conf_060=float(face_cfg.get("sim_at_conf_060", 0.35)),
            sim_at_conf_085=float(face_cfg.get("sim_at_conf_085", 0.55)),
        )
    except Exception as e:
        logger.error("Face engine unavailable (%s) — face topics disabled", e)

    object_engine = None
    try:
        object_engine = ObjectEngine(
            model_path=obj_cfg.get("model", "models/yolov8n.engine"),
            fallback_model=obj_cfg.get("fallback_model", "models/yolov8n.pt"),
            min_confidence=float(obj_cfg.get("min_confidence", 0.5)),
            labels=obj_cfg.get("labels"),
        )
    except Exception as e:
        logger.error("Object engine unavailable (%s) — object topics disabled", e)

    if face_engine is None and object_engine is None:
        logger.error("No detection engines available — nothing to publish. Exiting.")
        publisher.close()
        return 1

    # --- Presence state ----------------------------------------------
    faces = FacePresence(
        publisher,
        republish_seconds=float(face_cfg.get("republish_seconds", 7.0)),
        lost_after_seconds=float(face_cfg.get("lost_after_seconds", 5.0)),
    )
    objects = ObjectPresence(
        publisher,
        republish_seconds=float(obj_cfg.get("republish_seconds", 60.0)),
        prune_after_seconds=float(obj_cfg.get("prune_after_seconds", 10.0)),
    )
    occupancy = OccupancyTracker(
        publisher, smoothing_seconds=float(occ_cfg.get("smoothing_seconds", 5.0))
    )

    # --- Camera -------------------------------------------------------
    camera = RtspCamera(
        rtsp_url,
        codec=cam_cfg.get("codec", "h264"),
        latency_ms=int(cam_cfg.get("latency_ms", 200)),
        reconnect_delay=float(cam_cfg.get("reconnect_delay_seconds", 5.0)),
    )
    camera.start()

    stop = {"flag": False}

    def _handle_signal(signum, _frame):
        logger.info("Signal %s — shutting down", signum)
        stop["flag"] = True

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    face_interval = float(face_cfg.get("interval_seconds", 0.4))
    obj_interval = float(obj_cfg.get("interval_seconds", 1.0))
    next_face = 0.0
    next_obj = 0.0
    last_face_frame = -1
    last_obj_frame = -1

    logger.info("Vision service running — publishing to mother/vision/*")
    try:
        while not stop["flag"]:
            now = time.monotonic()
            latest = camera.get_latest()

            if latest is not None:
                frame_id, image = latest

                if face_engine and now >= next_face and frame_id != last_face_frame:
                    next_face = now + face_interval
                    last_face_frame = frame_id
                    try:
                        faces.observe(face_engine.identify_frame(image))
                    except Exception as e:
                        logger.error("Face pipeline error: %s", e)

                if object_engine and now >= next_obj and frame_id != last_obj_frame:
                    next_obj = now + obj_interval
                    last_obj_frame = frame_id
                    try:
                        dets = object_engine.detect(image)
                        objects.observe(
                            [(l, c) for l, c in dets if object_engine.wants(l)]
                        )
                        occupancy.observe(ObjectEngine.person_count(dets))
                    except Exception as e:
                        logger.error("Object pipeline error: %s", e)

            # Expire faces (-> face_lost), prune objects, decay occupancy
            faces.tick()
            objects.tick()
            occupancy.tick()

            time.sleep(0.05)
    finally:
        logger.info("Stopping camera and MQTT")
        camera.stop()
        publisher.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
