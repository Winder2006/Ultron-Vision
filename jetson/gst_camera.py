"""
RTSP capture with Jetson hardware decode.

Preferred path: GStreamer pipeline through OpenCV (JetPack's cv2 is built
with GStreamer) using nvv4l2decoder, so the 2K Tapo stream is decoded on
NVDEC instead of burning CPU:

    rtspsrc (TCP) -> rtph26xdepay -> h26xparse -> nvv4l2decoder
      -> nvvidconv (NVMM -> BGRx) -> videoconvert (BGR) -> appsink

Fallbacks, in order: software GStreamer decode, then FFMPEG over TCP.

Capture runs in its own thread and only keeps the LATEST frame — detection
pulls at its own pace and never backs up the stream.
"""

import logging
import os
import threading
import time
from typing import Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Used by the FFMPEG fallback; must be set before the first VideoCapture.
os.environ.setdefault(
    "OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp|stimeout;5000000"
)

_DEPAY = {
    "h264": "rtph264depay ! h264parse",
    "h265": "rtph265depay ! h265parse",
}


def nvdec_pipeline(url: str, codec: str = "h264", latency_ms: int = 200) -> str:
    depay = _DEPAY.get(codec, _DEPAY["h264"])
    return (
        'rtspsrc location="{url}" protocols=tcp latency={lat} drop-on-latency=true ! '
        "{depay} ! nvv4l2decoder ! "
        "nvvidconv ! video/x-raw,format=BGRx ! videoconvert ! video/x-raw,format=BGR ! "
        "appsink drop=true max-buffers=1 sync=false"
    ).format(url=url, lat=latency_ms, depay=depay)


def software_pipeline(url: str, latency_ms: int = 200) -> str:
    return (
        'rtspsrc location="{url}" protocols=tcp latency={lat} drop-on-latency=true ! '
        "decodebin ! videoconvert ! video/x-raw,format=BGR ! "
        "appsink drop=true max-buffers=1 sync=false"
    ).format(url=url, lat=latency_ms)


class RtspCamera:
    def __init__(
        self,
        rtsp_url: str,
        codec: str = "h264",
        latency_ms: int = 200,
        reconnect_delay: float = 5.0,
    ):
        self.rtsp_url = rtsp_url
        self.codec = codec
        self.latency_ms = latency_ms
        self.reconnect_delay = reconnect_delay

        self._cap: Optional[cv2.VideoCapture] = None
        self._backend = "none"
        self._latest: Optional[np.ndarray] = None
        self._frame_id = 0
        self._lock = threading.Lock()
        self._running = False
        self._connected = False
        self._thread: Optional[threading.Thread] = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def backend(self) -> str:
        return self._backend

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._capture_loop, name="RtspCamera", daemon=True
        )
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
        self._release()

    def get_latest(self) -> Optional[Tuple[int, np.ndarray]]:
        """(frame_id, BGR image) of the newest decoded frame, or None."""
        with self._lock:
            if self._latest is None:
                return None
            return self._frame_id, self._latest

    # ------------------------------------------------------------------

    def _try_open(self, pipeline: str, api: int, label: str) -> bool:
        try:
            cap = cv2.VideoCapture(pipeline, api)
            if cap.isOpened():
                ok, _ = cap.read()
                if ok:
                    self._cap = cap
                    self._backend = label
                    return True
            cap.release()
        except Exception as e:
            logger.debug("open failed (%s): %s", label, e)
        return False

    def _connect(self) -> bool:
        attempts = [
            (
                nvdec_pipeline(self.rtsp_url, self.codec, self.latency_ms),
                cv2.CAP_GSTREAMER,
                "gstreamer-nvdec",
            ),
            (
                software_pipeline(self.rtsp_url, self.latency_ms),
                cv2.CAP_GSTREAMER,
                "gstreamer-software",
            ),
            (self.rtsp_url, cv2.CAP_FFMPEG, "ffmpeg"),
        ]
        for pipeline, api, label in attempts:
            if self._try_open(pipeline, api, label):
                self._connected = True
                logger.info("Camera connected via %s", label)
                if label != "gstreamer-nvdec":
                    logger.warning(
                        "NOT using the Jetson hardware decoder (%s active). "
                        "Check codec setting (h264 vs h265) and that JetPack's "
                        "GStreamer OpenCV build is in use.", label
                    )
                return True
        logger.error("Failed to open RTSP stream with all backends")
        return False

    def _release(self):
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None
        self._connected = False

    def _capture_loop(self):
        while self._running:
            if not self._connected:
                if not self._connect():
                    time.sleep(self.reconnect_delay)
                    continue
            try:
                ok, image = self._cap.read()
                if not ok or image is None:
                    logger.warning("Frame read failed — reconnecting")
                    self._release()
                    continue
                with self._lock:
                    self._frame_id += 1
                    self._latest = image
            except Exception as e:
                logger.error("Capture error: %s", e)
                self._release()
                time.sleep(1.0)
