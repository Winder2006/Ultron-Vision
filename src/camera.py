"""
Camera Stream Capture - RTSP stream handling with threading and reconnection
"""

import os
import sys

# Force FFMPEG to use TCP for RTSP (far more reliable than default UDP on
# Reolink/IP cams) and fail fast instead of hanging forever on a dead stream.
# Must be set before the first cv2.VideoCapture() call.
os.environ.setdefault(
    "OPENCV_FFMPEG_CAPTURE_OPTIONS",
    "rtsp_transport;tcp|stimeout;5000000"
)

import cv2
import numpy as np
import threading
import time
import logging
from typing import Dict, List, Optional, Callable, Tuple
from dataclasses import dataclass
from queue import Queue, Empty
from datetime import datetime
import io
from PIL import Image

from .events import (
    event_bus, EventType, CameraStatus,
    create_camera_status_event
)

logger = logging.getLogger(__name__)

IS_WINDOWS = sys.platform.startswith("win")

# GStreamer rtspsrc jitter buffer (ms). Lower = more real-time, less tolerant
# of network jitter; drop-on-latency drops late frames instead of queueing.
RTSP_LATENCY_MS = 100
# A GStreamer capture that wedges on open/preroll must not block the capture
# thread forever — abandon it after this and fall through to the next backend.
RTSP_OPEN_TIMEOUT_S = 20.0


def nvdec_rtsp_pipeline(url: str, codec: str = "h264", latency_ms: int = RTSP_LATENCY_MS) -> str:
    """GStreamer pipeline decoding RTSP on the Jetson's NVDEC (nvv4l2decoder),
    so a 2K H.264 stream isn't software-decoded on the CPU."""
    depay = "rtph265depay ! h265parse" if codec == "h265" else "rtph264depay ! h264parse"
    return (
        'rtspsrc location="{url}" protocols=tcp latency={lat} drop-on-latency=true ! '
        "{depay} ! nvv4l2decoder ! "
        "nvvidconv ! video/x-raw,format=BGRx ! videoconvert ! video/x-raw,format=BGR ! "
        "appsink drop=true max-buffers=1 sync=false"
    ).format(url=url, lat=latency_ms, depay=depay)


def software_rtsp_pipeline(url: str, latency_ms: int = RTSP_LATENCY_MS) -> str:
    """Software-GStreamer fallback (decodebin auto-plugs a decoder)."""
    return (
        'rtspsrc location="{url}" protocols=tcp latency={lat} drop-on-latency=true ! '
        "decodebin ! videoconvert ! video/x-raw,format=BGR ! "
        "appsink drop=true max-buffers=1 sync=false"
    ).format(url=url, lat=latency_ms)


@dataclass
class CameraConfig:
    id: str
    name: str
    rtsp_url: str
    ptz_enabled: bool = False
    api_url: Optional[str] = None
    codec: str = "h264"  # RTSP codec for the NVDEC pipeline ("h264" or "h265")
    
    @property
    def is_webcam(self) -> bool:
        """Check if this is a local webcam source"""
        return self.rtsp_url.startswith("webcam:") or self.rtsp_url.isdigit()
    
    @property
    def webcam_index(self) -> int:
        """Get webcam device index"""
        if self.rtsp_url.startswith("webcam:"):
            return int(self.rtsp_url.split(":")[1])
        if self.rtsp_url.isdigit():
            return int(self.rtsp_url)
        return 0


@dataclass
class Frame:
    camera_id: str
    frame_id: int
    timestamp: datetime
    image: np.ndarray
    width: int
    height: int
    
    def to_jpeg(self, quality: int = 80) -> bytes:
        """Convert frame to JPEG bytes"""
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
        _, buffer = cv2.imencode('.jpg', self.image, encode_param)
        return buffer.tobytes()


class CameraStream:
    """
    Handles RTSP stream capture for a single camera with:
    - Threaded frame grabbing
    - Automatic reconnection
    - Frame queue for processing
    - Latest frame buffer for snapshots
    """
    
    def __init__(
        self,
        config: CameraConfig,
        frame_queue_size: int = 10,
        reconnect_delay: float = 5.0
    ):
        self.config = config
        self.frame_queue_size = frame_queue_size
        self.reconnect_delay = reconnect_delay
        
        self._cap: Optional[cv2.VideoCapture] = None
        self._frame_queue: Queue[Frame] = Queue(maxsize=frame_queue_size)
        self._latest_frame: Optional[Frame] = None
        # Lazy JPEG cache: (quality, max_width) -> (frame_id, bytes). Encoding
        # happens on the first consumer request per frame, not in the capture
        # thread.
        self._jpeg_cache: Dict[Tuple[int, Optional[int]], Tuple[int, bytes]] = {}
        self._frame_lock = threading.Lock()
        
        self._running = False
        self._connected = False
        self._backend = "none"  # active decode path (nvdec/software/ffmpeg/webcam)
        self._capture_thread: Optional[threading.Thread] = None
        self._frame_id = 0
        
        self._fps = 0.0
        self._fps_counter = 0
        self._fps_start_time = time.time()
        
        self._on_frame_callbacks: List[Callable[[Frame], None]] = []
        
        logger.info(f"CameraStream initialized for {config.name} ({config.id})")
    
    @property
    def is_connected(self) -> bool:
        return self._connected
    
    @property
    def fps(self) -> float:
        return self._fps
    
    @property
    def resolution(self) -> Optional[Tuple[int, int]]:
        if self._latest_frame:
            return (self._latest_frame.width, self._latest_frame.height)
        return None
    
    def add_frame_callback(self, callback: Callable[[Frame], None]):
        """Add callback to be called on each new frame"""
        self._on_frame_callbacks.append(callback)
    
    def remove_frame_callback(self, callback: Callable[[Frame], None]):
        """Remove frame callback"""
        if callback in self._on_frame_callbacks:
            self._on_frame_callbacks.remove(callback)
    
    def start(self):
        """Start the camera stream capture"""
        if self._running:
            logger.warning(f"Camera {self.config.id} already running")
            return
        
        self._running = True
        self._capture_thread = threading.Thread(
            target=self._capture_loop,
            name=f"Camera-{self.config.id}",
            daemon=True
        )
        self._capture_thread.start()
        logger.info(f"Camera {self.config.id} capture started")
    
    def stop(self):
        """Stop the camera stream capture"""
        self._running = False
        if self._capture_thread:
            self._capture_thread.join(timeout=5.0)
        self._disconnect()
        logger.info(f"Camera {self.config.id} capture stopped")
    
    def get_frame(self, timeout: float = 1.0) -> Optional[Frame]:
        """Get next frame from queue (blocking)"""
        try:
            return self._frame_queue.get(timeout=timeout)
        except Empty:
            return None
    
    def get_latest_frame(self) -> Optional[Frame]:
        """Get the most recent frame (non-blocking)"""
        with self._frame_lock:
            return self._latest_frame
    
    def get_latest_jpeg(
        self, quality: int = 80, max_width: Optional[int] = None
    ) -> Optional[bytes]:
        """Get the most recent frame as JPEG bytes.

        Encoded lazily and cached per (frame, quality, max_width), so N stream
        clients cost one encode per frame and an unwatched camera costs zero.

        max_width downscales for browser preview — a full 2K frame is ~10x the
        pixels a live-view canvas needs, and decoding it per-frame is the main
        source of UI lag. Detection still runs on the full-res frame.
        """
        key = (quality, max_width)
        with self._frame_lock:
            frame = self._latest_frame
            if frame is None:
                return None
            cached = self._jpeg_cache.get(key)
            if cached is not None and cached[0] == frame.frame_id:
                return cached[1]
        # Encode (and optionally downscale) outside the lock — never block
        # the capture thread on this.
        image = frame.image
        if max_width and frame.width > max_width:
            new_h = int(round(frame.height * (max_width / float(frame.width))))
            image = cv2.resize(image, (max_width, new_h), interpolation=cv2.INTER_AREA)
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
        ok, buffer = cv2.imencode('.jpg', image, encode_param)
        if not ok:
            return None
        jpeg = buffer.tobytes()
        with self._frame_lock:
            if self._latest_frame is frame:
                self._jpeg_cache[key] = (frame.frame_id, jpeg)
        return jpeg
    
    def get_status(self) -> CameraStatus:
        """Get current camera status"""
        return CameraStatus(
            camera_id=self.config.id,
            online=self._connected,
            fps=self._fps,
            resolution=self.resolution,
            error=None if self._connected else "Disconnected"
        )
    
    def _connect(self) -> bool:
        """Connect to the RTSP stream or webcam"""
        try:
            if not self.config.is_webcam:
                return self._connect_rtsp()

            # Connect to local webcam
            webcam_idx = self.config.webcam_index
            logger.info(f"Connecting to webcam {webcam_idx} for camera {self.config.id}")
            # CAP_DSHOW is Windows-only; on Linux/Jetson use V4L2.
            if IS_WINDOWS:
                self._cap = cv2.VideoCapture(webcam_idx, cv2.CAP_DSHOW)
            else:
                self._cap = cv2.VideoCapture(webcam_idx, cv2.CAP_V4L2)

            # Set webcam properties
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            self._cap.set(cv2.CAP_PROP_FPS, 30)
            self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

            if self._cap.isOpened():
                ret, _ = self._cap.read()
                if ret:
                    self._connected = True
                    self._backend = "webcam"
                    logger.info(f"Camera {self.config.id} connected successfully (webcam)")
                    self._publish_status()
                    return True

            logger.error(f"Failed to connect to camera {self.config.id}")
            self._disconnect()
            return False

        except Exception as e:
            logger.error(f"Error connecting to camera {self.config.id}: {e}")
            self._disconnect()
            return False

    def _open_capture_guarded(self, source, api, label: str):
        """Open a VideoCapture and read one test frame, but abandon the attempt
        after RTSP_OPEN_TIMEOUT_S. A GStreamer/NVDEC pipeline can wedge on
        open/preroll with no internal timeout, which previously blocked the
        capture thread forever; the watchdog lets us fall through to the next
        backend instead. Returns the opened cap, or None.
        """
        holder = {}

        def _open():
            try:
                cap = cv2.VideoCapture(source, api)
                if api == cv2.CAP_FFMPEG:
                    try:
                        cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 8000)
                        cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 8000)
                    except AttributeError:
                        pass
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                if cap.isOpened():
                    ok, _ = cap.read()
                    if ok:
                        holder["cap"] = cap
                        return
                cap.release()
            except Exception as e:
                logger.debug(f"{label} open error for {self.config.id}: {e}")

        th = threading.Thread(target=_open, name=f"open-{self.config.id}", daemon=True)
        th.start()
        th.join(RTSP_OPEN_TIMEOUT_S)
        if "cap" in holder:
            return holder["cap"]
        if th.is_alive():
            logger.warning(
                f"{label} open timed out (>{RTSP_OPEN_TIMEOUT_S}s) for "
                f"{self.config.id} — abandoning, trying next backend"
            )
        return None

    def _connect_rtsp(self) -> bool:
        """Open an RTSP stream, preferring Jetson hardware decode.

        Tries, in order: NVDEC via GStreamer (nvv4l2decoder) -> software
        GStreamer -> FFMPEG. Hardware decode cuts latency and CPU vs
        software-decoding 2K H.264. Each attempt is guarded by a watchdog so a
        wedged pipeline can't block the capture thread — it just falls through
        to the next (the FFMPEG path is the proven fallback).
        """
        url = self.config.rtsp_url
        codec = getattr(self.config, "codec", "h264") or "h264"

        attempts = []
        # GStreamer is a JetPack/Linux OpenCV feature; on Windows (webcam dev,
        # pip OpenCV has no GStreamer) go straight to FFMPEG.
        if not IS_WINDOWS:
            attempts.append((nvdec_rtsp_pipeline(url, codec), cv2.CAP_GSTREAMER, "gstreamer-nvdec"))
            attempts.append((software_rtsp_pipeline(url), cv2.CAP_GSTREAMER, "gstreamer-software"))
        attempts.append((url, cv2.CAP_FFMPEG, "ffmpeg"))

        for source, api, label in attempts:
            logger.info(f"Connecting to camera {self.config.id} via {label}")
            cap = self._open_capture_guarded(source, api, label)
            if cap is not None:
                self._cap = cap
                self._backend = label
                self._connected = True
                logger.info(f"Camera {self.config.id} connected via {label}")
                if label != "gstreamer-nvdec":
                    logger.warning(
                        f"Camera {self.config.id} is NOT using NVDEC hardware "
                        f"decode ({label}) — the stream is decoded on the CPU."
                    )
                self._publish_status()
                return True

        logger.error(f"Failed to connect to camera {self.config.id} (all backends)")
        self._disconnect()
        return False


    def _disconnect(self):
        """Disconnect from the RTSP stream"""
        if self._cap:
            self._cap.release()
            self._cap = None
        
        was_connected = self._connected
        self._connected = False
        self._backend = "none"

        if was_connected:
            logger.info(f"Camera {self.config.id} disconnected")
            self._publish_status()
    
    def _publish_status(self):
        """Publish camera status event"""
        try:
            event = create_camera_status_event(self.get_status())
            event_bus.publish_sync(event)
        except Exception as e:
            logger.error(f"Error publishing camera status: {e}")
    
    def _capture_loop(self):
        """Main capture loop running in separate thread"""
        while self._running:
            if not self._connected:
                if not self._connect():
                    time.sleep(self.reconnect_delay)
                    continue
            
            try:
                ret, image = self._cap.read()
                
                if not ret:
                    logger.warning(f"Camera {self.config.id} frame read failed")
                    self._disconnect()
                    continue
                
                # Create frame object
                self._frame_id += 1
                frame = Frame(
                    camera_id=self.config.id,
                    frame_id=self._frame_id,
                    timestamp=datetime.now(),
                    image=image,
                    width=image.shape[1],
                    height=image.shape[0]
                )
                
                # Update latest frame (JPEG encoding is deferred to
                # get_latest_jpeg — keep the capture loop lean)
                with self._frame_lock:
                    self._latest_frame = frame
                
                # Add to queue (non-blocking, drop old frames if full)
                try:
                    # Remove old frame if queue is full
                    if self._frame_queue.full():
                        try:
                            self._frame_queue.get_nowait()
                        except Empty:
                            pass
                    self._frame_queue.put_nowait(frame)
                except:
                    pass
                
                # Call frame callbacks
                for callback in self._on_frame_callbacks:
                    try:
                        callback(frame)
                    except Exception as e:
                        logger.error(f"Error in frame callback: {e}")
                
                # Update FPS counter
                self._fps_counter += 1
                elapsed = time.time() - self._fps_start_time
                if elapsed >= 1.0:
                    self._fps = self._fps_counter / elapsed
                    self._fps_counter = 0
                    self._fps_start_time = time.time()
                
            except Exception as e:
                logger.error(f"Error in capture loop for {self.config.id}: {e}")
                self._disconnect()
                time.sleep(1.0)


class CameraManager:
    """
    Manages multiple camera streams
    """
    
    _instance: Optional['CameraManager'] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._cameras: Dict[str, CameraStream] = {}
        self._configs: Dict[str, CameraConfig] = {}
        self._initialized = True
        logger.info("CameraManager initialized")
    
    def add_camera(self, config: CameraConfig) -> CameraStream:
        """Add and start a camera"""
        if config.id in self._cameras:
            logger.warning(f"Camera {config.id} already exists")
            return self._cameras[config.id]
        
        stream = CameraStream(config)
        self._cameras[config.id] = stream
        self._configs[config.id] = config
        return stream
    
    def get_camera(self, camera_id: str) -> Optional[CameraStream]:
        """Get camera stream by ID"""
        return self._cameras.get(camera_id)
    
    def get_all_cameras(self) -> Dict[str, CameraStream]:
        """Get all camera streams"""
        return self._cameras.copy()
    
    def get_config(self, camera_id: str) -> Optional[CameraConfig]:
        """Get camera config by ID"""
        return self._configs.get(camera_id)
    
    def get_all_configs(self) -> Dict[str, CameraConfig]:
        """Get all camera configs"""
        return self._configs.copy()
    
    def start_all(self):
        """Start all cameras"""
        for camera in self._cameras.values():
            camera.start()
        logger.info(f"Started {len(self._cameras)} cameras")
    
    def stop_all(self):
        """Stop all cameras"""
        for camera in self._cameras.values():
            camera.stop()
        logger.info("All cameras stopped")
    
    def get_statuses(self) -> List[CameraStatus]:
        """Get status of all cameras"""
        return [camera.get_status() for camera in self._cameras.values()]
    
    def remove_camera(self, camera_id: str):
        """Remove a camera"""
        if camera_id in self._cameras:
            self._cameras[camera_id].stop()
            del self._cameras[camera_id]
            del self._configs[camera_id]
            logger.info(f"Camera {camera_id} removed")


# Global camera manager instance
camera_manager = CameraManager()

