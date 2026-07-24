"""
Object detection via Ultralytics YOLO, preferring a TensorRT .engine built on
the Jetson. Build it once (takes a few minutes, must be done ON the Jetson —
TensorRT engines are not portable across GPUs):

    yolo export model=yolov8n.pt format=engine half=True

Falls back to the .pt (PyTorch/CUDA) if no engine file exists.
"""

import logging
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


class ObjectEngine:
    def __init__(
        self,
        model_path: str = "models/yolov8n.engine",
        fallback_model: str = "models/yolov8n.pt",
        min_confidence: float = 0.5,
        labels: Optional[List[str]] = None,
    ):
        self.min_confidence = min_confidence
        self.labels = set(labels) if labels else None

        from ultralytics import YOLO  # heavy import, keep lazy

        path = Path(model_path)
        if not path.exists():
            logger.warning(
                "TensorRT engine %s not found — falling back to %s "
                "(build the engine with: yolo export model=%s format=engine half=True)",
                model_path, fallback_model, fallback_model,
            )
            path = Path(fallback_model)
        # Ultralytics can't infer the task from a bare .engine file
        self.model = YOLO(str(path), task="detect")
        logger.info("ObjectEngine ready (%s)", path)

    def detect(self, frame_bgr: np.ndarray) -> List[Tuple[str, float]]:
        """Returns ALL [(label, confidence)] above min_confidence.

        Unfiltered on purpose: occupancy needs "person" counts regardless of
        the publish label set — apply `wants()` before publishing.
        """
        results = self.model.predict(
            frame_bgr, conf=self.min_confidence, verbose=False
        )
        out: List[Tuple[str, float]] = []
        if not results:
            return out
        res = results[0]
        names = res.names
        for box in res.boxes:
            out.append((names[int(box.cls[0])], float(box.conf[0])))
        return out

    def wants(self, label: str) -> bool:
        """Should this label be published as object_detected?"""
        return self.labels is None or label in self.labels

    @staticmethod
    def person_count(detections: List[Tuple[str, float]]) -> int:
        return sum(1 for label, _ in detections if label == "person")
