"""
Recording - Video clips and snapshot capture
"""

import cv2
import numpy as np
import logging
import threading
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque
import time
import shutil

from .events import event_bus, EventType
from .camera import Frame, camera_manager

logger = logging.getLogger(__name__)


@dataclass
class RecordingConfig:
    enabled: bool = True
    path: str = "data/recordings"
    snapshot_path: str = "data/snapshots"
    max_days: int = 14
    event_buffer_seconds: int = 30
    continuous_segment_minutes: int = 15
    fps: int = 15
    codec: str = "mp4v"


@dataclass
class Recording:
    id: str
    camera_id: str
    start_time: datetime
    end_time: Optional[datetime]
    file_path: str
    recording_type: str  # continuous, event
    event_type: Optional[str] = None
    thumbnail_path: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "camera_id": self.camera_id,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "file_path": self.file_path,
            "type": self.recording_type,
            "event_type": self.event_type,
            "thumbnail_path": self.thumbnail_path
        }


@dataclass
class Snapshot:
    id: str
    camera_id: str
    timestamp: datetime
    file_path: str
    event_type: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "camera_id": self.camera_id,
            "timestamp": self.timestamp.isoformat(),
            "file_path": self.file_path,
            "event_type": self.event_type
        }


class FrameBuffer:
    """Circular buffer for storing recent frames"""
    
    def __init__(self, max_seconds: int = 30, fps: int = 15):
        self.max_frames = max_seconds * fps
        self._buffer: deque[Frame] = deque(maxlen=self.max_frames)
        self._lock = threading.Lock()
    
    def add(self, frame: Frame):
        with self._lock:
            self._buffer.append(frame)
    
    def get_frames(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> List[Frame]:
        with self._lock:
            frames = list(self._buffer)
        
        if start_time:
            frames = [f for f in frames if f.timestamp >= start_time]
        
        if end_time:
            frames = [f for f in frames if f.timestamp <= end_time]
        
        return frames
    
    def clear(self):
        with self._lock:
            self._buffer.clear()


class CameraRecorder:
    """Records video and snapshots for a single camera"""
    
    def __init__(self, camera_id: str, config: RecordingConfig):
        self.camera_id = camera_id
        self.config = config
        
        # Paths
        self.recording_path = Path(config.path) / camera_id
        self.snapshot_path = Path(config.snapshot_path) / camera_id
        self.recording_path.mkdir(parents=True, exist_ok=True)
        self.snapshot_path.mkdir(parents=True, exist_ok=True)
        
        # Frame buffer for event recording
        self._frame_buffer = FrameBuffer(
            max_seconds=config.event_buffer_seconds,
            fps=config.fps
        )
        
        # Current recording state
        self._current_writer: Optional[cv2.VideoWriter] = None
        self._current_recording: Optional[Recording] = None
        self._recording_start: Optional[datetime] = None
        
        # Recording lists
        self._recordings: List[Recording] = []
        self._snapshots: List[Snapshot] = []
        self._lock = threading.Lock()
        
        # Frame size (set from first frame)
        self._frame_size: Optional[Tuple[int, int]] = None
        
        logger.info(f"CameraRecorder initialized for {camera_id}")
    
    def add_frame(self, frame: Frame):
        """Add frame to buffer and current recording"""
        # Update frame size
        if self._frame_size is None:
            self._frame_size = (frame.width, frame.height)
        
        # Add to buffer
        self._frame_buffer.add(frame)
        
        # Write to current recording
        if self._current_writer:
            self._current_writer.write(frame.image)
            
            # Check segment duration
            if self._recording_start:
                elapsed = (datetime.now() - self._recording_start).total_seconds()
                if elapsed >= self.config.continuous_segment_minutes * 60:
                    self._finalize_recording()
                    self._start_continuous_recording()
    
    def _get_codec(self) -> int:
        """Get video codec fourcc"""
        return cv2.VideoWriter_fourcc(*self.config.codec)
    
    def _start_continuous_recording(self):
        """Start a new continuous recording segment"""
        if not self.config.enabled or self._frame_size is None:
            return
        
        timestamp = datetime.now()
        filename = timestamp.strftime("%Y%m%d_%H%M%S") + ".mp4"
        file_path = self.recording_path / filename
        
        self._current_writer = cv2.VideoWriter(
            str(file_path),
            self._get_codec(),
            self.config.fps,
            self._frame_size
        )
        
        recording_id = f"{self.camera_id}_{timestamp.strftime('%Y%m%d%H%M%S')}"
        
        self._current_recording = Recording(
            id=recording_id,
            camera_id=self.camera_id,
            start_time=timestamp,
            end_time=None,
            file_path=str(file_path),
            recording_type="continuous"
        )
        
        self._recording_start = timestamp
        logger.info(f"Started continuous recording: {file_path}")
    
    def _finalize_recording(self):
        """Finalize current recording"""
        if self._current_writer:
            self._current_writer.release()
            self._current_writer = None
        
        if self._current_recording:
            self._current_recording.end_time = datetime.now()
            
            with self._lock:
                self._recordings.append(self._current_recording)
            
            logger.info(f"Finalized recording: {self._current_recording.file_path}")
            self._current_recording = None
        
        self._recording_start = None
    
    def start_recording(self):
        """Start continuous recording"""
        if self._current_writer:
            return
        self._start_continuous_recording()
    
    def stop_recording(self):
        """Stop current recording"""
        self._finalize_recording()
    
    def record_event(
        self,
        event_type: str,
        pre_seconds: Optional[int] = None,
        post_seconds: Optional[int] = None
    ) -> Optional[Recording]:
        """
        Record an event with pre and post buffer.
        Returns the Recording object.
        """
        if not self.config.enabled or self._frame_size is None:
            return None
        
        pre_seconds = pre_seconds or self.config.event_buffer_seconds
        post_seconds = post_seconds or self.config.event_buffer_seconds
        
        timestamp = datetime.now()
        filename = f"event_{event_type}_{timestamp.strftime('%Y%m%d_%H%M%S')}.mp4"
        file_path = self.recording_path / filename
        
        # Get frames from buffer (pre-event)
        start_time = timestamp - timedelta(seconds=pre_seconds)
        pre_frames = self._frame_buffer.get_frames(start_time=start_time)
        
        if not pre_frames:
            logger.warning("No frames in buffer for event recording")
            return None
        
        # Write pre-event frames
        writer = cv2.VideoWriter(
            str(file_path),
            self._get_codec(),
            self.config.fps,
            self._frame_size
        )
        
        for frame in pre_frames:
            writer.write(frame.image)
        
        # Continue recording for post-event duration
        # This would normally be async, but for simplicity we just write pre-event
        writer.release()
        
        recording_id = f"{self.camera_id}_event_{timestamp.strftime('%Y%m%d%H%M%S')}"
        
        recording = Recording(
            id=recording_id,
            camera_id=self.camera_id,
            start_time=start_time,
            end_time=timestamp,
            file_path=str(file_path),
            recording_type="event",
            event_type=event_type
        )
        
        # Create thumbnail
        if pre_frames:
            thumb_path = self.snapshot_path / f"{recording_id}_thumb.jpg"
            cv2.imwrite(str(thumb_path), pre_frames[-1].image)
            recording.thumbnail_path = str(thumb_path)
        
        with self._lock:
            self._recordings.append(recording)
        
        logger.info(f"Created event recording: {file_path}")
        return recording
    
    def take_snapshot(
        self,
        event_type: Optional[str] = None
    ) -> Optional[Snapshot]:
        """Take a snapshot from current frame"""
        camera = camera_manager.get_camera(self.camera_id)
        if not camera:
            return None
        
        frame = camera.get_latest_frame()
        if not frame:
            return None
        
        timestamp = datetime.now()
        
        if event_type:
            filename = f"{event_type}_{timestamp.strftime('%Y%m%d_%H%M%S')}.jpg"
        else:
            filename = f"snapshot_{timestamp.strftime('%Y%m%d_%H%M%S')}.jpg"
        
        file_path = self.snapshot_path / filename
        cv2.imwrite(str(file_path), frame.image)
        
        snapshot_id = f"{self.camera_id}_{timestamp.strftime('%Y%m%d%H%M%S%f')}"
        
        snapshot = Snapshot(
            id=snapshot_id,
            camera_id=self.camera_id,
            timestamp=timestamp,
            file_path=str(file_path),
            event_type=event_type
        )
        
        with self._lock:
            self._snapshots.append(snapshot)
        
        logger.info(f"Captured snapshot: {file_path}")
        return snapshot
    
    def get_recordings(
        self,
        recording_type: Optional[str] = None,
        since: Optional[datetime] = None
    ) -> List[Recording]:
        """Get recordings with optional filters"""
        with self._lock:
            recordings = self._recordings.copy()
        
        if recording_type:
            recordings = [r for r in recordings if r.recording_type == recording_type]
        
        if since:
            recordings = [r for r in recordings if r.start_time >= since]
        
        return recordings
    
    def get_snapshots(self, since: Optional[datetime] = None) -> List[Snapshot]:
        """Get snapshots with optional time filter"""
        with self._lock:
            snapshots = self._snapshots.copy()
        
        if since:
            snapshots = [s for s in snapshots if s.timestamp >= since]
        
        return snapshots
    
    def cleanup_old(self):
        """Remove recordings older than max_days"""
        cutoff = datetime.now() - timedelta(days=self.config.max_days)
        
        # Clean recording files
        for file_path in self.recording_path.glob("*.mp4"):
            try:
                mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
                if mtime < cutoff:
                    file_path.unlink()
                    logger.info(f"Deleted old recording: {file_path}")
            except Exception as e:
                logger.error(f"Error cleaning up {file_path}: {e}")
        
        # Clean snapshot files
        for file_path in self.snapshot_path.glob("*.jpg"):
            try:
                mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
                if mtime < cutoff:
                    file_path.unlink()
                    logger.info(f"Deleted old snapshot: {file_path}")
            except Exception as e:
                logger.error(f"Error cleaning up {file_path}: {e}")
        
        # Clean recordings list
        with self._lock:
            self._recordings = [r for r in self._recordings if r.start_time >= cutoff]
            self._snapshots = [s for s in self._snapshots if s.timestamp >= cutoff]


class RecorderManager:
    """
    Manages recorders for all cameras.
    """
    
    _instance: Optional['RecorderManager'] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._recorders: Dict[str, CameraRecorder] = {}
        self._config = RecordingConfig()
        self._cleanup_thread: Optional[threading.Thread] = None
        self._running = False
        self._initialized = True
        
        # Track unknown faces to avoid repeated snapshots
        # Key: camera_id, Value: set of bbox signatures we've already snapshotted
        self._snapshotted_unknowns: Dict[str, Dict[str, datetime]] = {}
        self._snapshot_cooldown_seconds = 60  # Don't re-snapshot same person for 60 seconds
        
        # Subscribe to events for automatic recording
        event_bus.subscribe(EventType.FACES_DETECTED, self._on_faces_detected)
        event_bus.subscribe(EventType.ACTIVITY_ALERT, self._on_activity_alert)
        
        logger.info("RecorderManager initialized")
    
    def configure(self, config: RecordingConfig):
        """Update configuration"""
        self._config = config
    
    def get_recorder(self, camera_id: str) -> CameraRecorder:
        """Get or create recorder for camera"""
        if camera_id not in self._recorders:
            self._recorders[camera_id] = CameraRecorder(camera_id, self._config)
        return self._recorders[camera_id]
    
    def add_frame(self, frame: Frame):
        """Add frame to appropriate recorder"""
        recorder = self.get_recorder(frame.camera_id)
        recorder.add_frame(frame)
    
    def start_all(self):
        """Start recording on all cameras"""
        for recorder in self._recorders.values():
            recorder.start_recording()
        
        # Start cleanup thread
        self._running = True
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop,
            daemon=True
        )
        self._cleanup_thread.start()
        
        logger.info("Started all recorders")
    
    def stop_all(self):
        """Stop recording on all cameras"""
        self._running = False
        
        for recorder in self._recorders.values():
            recorder.stop_recording()
        
        logger.info("Stopped all recorders")
    
    def _cleanup_loop(self):
        """Periodic cleanup of old recordings"""
        while self._running:
            for recorder in self._recorders.values():
                recorder.cleanup_old()
            
            # Run cleanup every hour
            time.sleep(3600)
    
    def _on_faces_detected(self, event):
        """Take snapshot on NEW unknown face detection only"""
        faces = event.data.get("faces", [])
        camera_id = event.camera_id
        
        # Only process unknown faces
        unknown = [f for f in faces if not f.get("known", True)]
        
        if not unknown:
            # No unknown faces - clear the "currently tracking unknown" state
            if camera_id in self._snapshotted_unknowns:
                self._snapshotted_unknowns[camera_id]["has_unknown"] = False
            return
        
        now = datetime.now()
        
        # Initialize tracking for this camera if needed
        if camera_id not in self._snapshotted_unknowns:
            self._snapshotted_unknowns[camera_id] = {
                "last_snapshot": None,
                "has_unknown": False
            }
        
        tracked = self._snapshotted_unknowns[camera_id]
        
        # Check if we were already tracking an unknown person
        was_tracking = tracked.get("has_unknown", False)
        last_snapshot = tracked.get("last_snapshot")
        
        # Mark that we currently see an unknown
        tracked["has_unknown"] = True
        
        # Only snapshot if:
        # 1. We weren't tracking an unknown before (new person appeared), OR
        # 2. It's been longer than cooldown since last snapshot AND unknown left and came back
        should_snapshot = False
        
        if not was_tracking:
            # New unknown person appeared!
            should_snapshot = True
        elif last_snapshot:
            # Check cooldown
            elapsed = (now - last_snapshot).total_seconds()
            if elapsed > self._snapshot_cooldown_seconds:
                # Enough time passed - but only if person left and came back
                # (we already have "was_tracking" so this won't fire)
                pass
        
        if should_snapshot:
            recorder = self.get_recorder(camera_id)
            recorder.take_snapshot(event_type="unknown_face")
            tracked["last_snapshot"] = now
            logger.info(f"Snapshot taken for new unknown face on {camera_id}")
    
    def _on_activity_alert(self, event):
        """Record event on activity alert"""
        alert = event.data
        recorder = self.get_recorder(event.camera_id)
        
        # Record event clip
        recorder.record_event(alert.get("alert_type", "alert"))
    
    def take_snapshot(
        self,
        camera_id: str,
        event_type: Optional[str] = None
    ) -> Optional[Snapshot]:
        """Take snapshot from camera"""
        recorder = self.get_recorder(camera_id)
        return recorder.take_snapshot(event_type)
    
    def get_all_recordings(
        self,
        camera_id: Optional[str] = None,
        recording_type: Optional[str] = None,
        since: Optional[datetime] = None
    ) -> List[Recording]:
        """Get recordings from all cameras"""
        recordings = []
        
        recorders = [self._recorders[camera_id]] if camera_id else self._recorders.values()
        
        for recorder in recorders:
            recordings.extend(recorder.get_recordings(recording_type, since))
        
        # Sort by start time descending
        recordings.sort(key=lambda r: r.start_time, reverse=True)
        return recordings
    
    def get_all_snapshots(
        self,
        camera_id: Optional[str] = None,
        since: Optional[datetime] = None
    ) -> List[Snapshot]:
        """Get snapshots from all cameras"""
        snapshots = []
        
        recorders = [self._recorders[camera_id]] if camera_id else self._recorders.values()
        
        for recorder in recorders:
            snapshots.extend(recorder.get_snapshots(since))
        
        # Sort by timestamp descending
        snapshots.sort(key=lambda s: s.timestamp, reverse=True)
        return snapshots


# Global recorder manager instance
recorder_manager = RecorderManager()

