"""
Presence state machines — translate raw per-frame detections into the event
cadence Mother expects:

  faces:     publish on arrival, re-publish every ~5-10s while in frame
             (Mother stales a face after 120s of silence), face_lost ONCE
             when the face leaves the frame.
  objects:   publish on arrival, re-publish periodically while visible
             (Mother staleness window: 300s). No "lost" event in the contract.
  occupancy: publish on change only, retained. person_count is smoothed with
             a sliding-window max so a single missed YOLO frame doesn't flap
             the room to empty.

All timing uses time.monotonic(); wall-clock ts for payloads is stamped by
the publisher at send time.
"""

import logging
import time
from collections import deque
from typing import Dict, List, Optional, Tuple

# `publisher` below is duck-typed (anything with the VisionPublisher topic
# methods) so these state machines can be exercised without an MQTT stack.

logger = logging.getLogger(__name__)


class FacePresence:
    def __init__(
        self,
        publisher,
        republish_seconds: float = 7.0,
        lost_after_seconds: float = 5.0,
    ):
        self.publisher = publisher
        self.republish_seconds = republish_seconds
        self.lost_after_seconds = lost_after_seconds
        # name -> {"last_seen": t, "last_pub": t}
        self._present: Dict[str, Dict[str, float]] = {}

    def observe(self, detections: List[Tuple[str, float]], now: Optional[float] = None):
        """Feed one frame's worth of (name, confidence) detections."""
        now = time.monotonic() if now is None else now
        # Collapse duplicates (e.g. two unknown faces) to the best confidence;
        # identity is by name, so "unknown" is tracked as a single presence.
        best: Dict[str, float] = {}
        for name, conf in detections:
            if name not in best or conf > best[name]:
                best[name] = conf

        for name, conf in best.items():
            entry = self._present.get(name)
            if entry is None:
                self._present[name] = {"last_seen": now, "last_pub": now}
                self.publisher.face_detected(name, conf)
                logger.info("face arrived: %s (%.2f)", name, conf)
            else:
                entry["last_seen"] = now
                if now - entry["last_pub"] >= self.republish_seconds:
                    entry["last_pub"] = now
                    self.publisher.face_detected(name, conf)

    def tick(self, now: Optional[float] = None):
        """Expire faces not seen recently -> face_lost (published once)."""
        now = time.monotonic() if now is None else now
        for name in list(self._present):
            if now - self._present[name]["last_seen"] >= self.lost_after_seconds:
                del self._present[name]
                self.publisher.face_lost(name)
                logger.info("face lost: %s", name)


class ObjectPresence:
    def __init__(
        self,
        publisher,
        republish_seconds: float = 60.0,
        prune_after_seconds: float = 10.0,
    ):
        self.publisher = publisher
        self.republish_seconds = republish_seconds
        self.prune_after_seconds = prune_after_seconds
        # label -> {"last_seen": t, "last_pub": t}
        self._present: Dict[str, Dict[str, float]] = {}

    def observe(self, detections: List[Tuple[str, float]], now: Optional[float] = None):
        now = time.monotonic() if now is None else now
        best: Dict[str, float] = {}
        for label, conf in detections:
            if label not in best or conf > best[label]:
                best[label] = conf

        for label, conf in best.items():
            entry = self._present.get(label)
            if entry is None:
                self._present[label] = {"last_seen": now, "last_pub": now}
                self.publisher.object_detected(label, conf)
                logger.info("object arrived: %s (%.2f)", label, conf)
            else:
                entry["last_seen"] = now
                if now - entry["last_pub"] >= self.republish_seconds:
                    entry["last_pub"] = now
                    self.publisher.object_detected(label, conf)

    def tick(self, now: Optional[float] = None):
        """Silently forget stale objects so a re-appearance publishes fresh.
        (No object_lost event in the contract — Mother uses its 300s window.)"""
        now = time.monotonic() if now is None else now
        for label in list(self._present):
            if now - self._present[label]["last_seen"] >= self.prune_after_seconds:
                del self._present[label]


class OccupancyTracker:
    def __init__(self, publisher, smoothing_seconds: float = 5.0):
        self.publisher = publisher
        self.smoothing_seconds = smoothing_seconds
        self._samples = deque()  # (monotonic_t, person_count)
        self._published: Optional[Tuple[bool, int]] = None

    def observe(self, person_count: int, now: Optional[float] = None):
        now = time.monotonic() if now is None else now
        self._samples.append((now, person_count))
        self._evaluate(now)

    def tick(self, now: Optional[float] = None):
        # Lets the count decay to 0 when detections stop entirely
        # (e.g. camera offline) once the window empties.
        self._evaluate(time.monotonic() if now is None else now)

    def _evaluate(self, now: float):
        while self._samples and now - self._samples[0][0] > self.smoothing_seconds:
            self._samples.popleft()
        count = max((c for _, c in self._samples), default=0)
        state = (count > 0, count)
        if state != self._published:
            self._published = state
            self.publisher.room_occupancy(*state)
            logger.info("occupancy changed: occupied=%s count=%d", *state)
