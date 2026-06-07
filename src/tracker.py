"""
Person Tracker - Follow specific person with PTZ camera
"""

import asyncio
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
import threading

from .events import (
    event_bus, EventType, Event, TrackingStatus,
    create_tracking_event
)
from .ptz_control import ptz_manager
from .face_recognition import FaceDetection

logger = logging.getLogger(__name__)


@dataclass
class TrackingConfig:
    # PTZ movement speeds
    slow_speed: int = 10
    medium_speed: int = 25
    fast_speed: int = 40
    
    # Deadzone - area in center where no movement is needed (percentage)
    deadzone_x: float = 0.2  # 20% of frame width
    deadzone_y: float = 0.2  # 20% of frame height
    
    # Lost target timeout
    lost_timeout_seconds: float = 5.0
    
    # Smoothing (higher = slower response)
    smoothing_factor: float = 0.3


class PersonTracker:
    """
    Tracks a specific person and controls PTZ to keep them centered.
    Uses smooth movement to avoid jerky tracking.
    """
    
    def __init__(self, camera_id: str, frame_size: Tuple[int, int] = (1920, 1080)):
        self.camera_id = camera_id
        self.frame_width, self.frame_height = frame_size
        self.config = TrackingConfig()
        
        self._target_name: Optional[str] = None
        self._tracking_state: str = "idle"  # idle, tracking, searching, lost
        self._last_bbox: Optional[List[int]] = None
        self._last_seen: Optional[datetime] = None
        self._running = False
        self._track_task: Optional[asyncio.Task] = None
        self._lock = threading.Lock()
        
        # Smoothed position for smoother PTZ movement
        self._smoothed_x: float = 0.5
        self._smoothed_y: float = 0.5
        
        logger.info(f"PersonTracker initialized for camera {camera_id}")
    
    def configure(self, config: TrackingConfig):
        """Update configuration"""
        self.config = config
    
    def set_frame_size(self, width: int, height: int):
        """Update frame size for position calculations"""
        self.frame_width = width
        self.frame_height = height
    
    def start_tracking(self, target_name: str):
        """Start tracking a specific person"""
        with self._lock:
            self._target_name = target_name
            self._tracking_state = "searching"
            self._running = True
            
            logger.info(f"Started tracking {target_name} on camera {self.camera_id}")
            self._emit_status()
    
    def stop_tracking(self):
        """Stop tracking"""
        with self._lock:
            self._target_name = None
            self._tracking_state = "idle"
            self._running = False
            self._last_bbox = None
            self._last_seen = None
            
            logger.info(f"Stopped tracking on camera {self.camera_id}")
            self._emit_status()
    
    def update_faces(self, faces: List[FaceDetection]):
        """
        Update with detected faces.
        Called by main processing loop.
        """
        if not self._running or not self._target_name:
            return
        
        with self._lock:
            # Find target face
            target_face = None
            for face in faces:
                if face.name == self._target_name:
                    target_face = face
                    break
            
            if target_face:
                self._last_bbox = target_face.bbox
                self._last_seen = datetime.now()
                self._tracking_state = "tracking"
            else:
                # Check timeout
                if self._last_seen:
                    elapsed = (datetime.now() - self._last_seen).total_seconds()
                    
                    if elapsed > self.config.lost_timeout_seconds:
                        self._tracking_state = "lost"
                    else:
                        self._tracking_state = "searching"
                else:
                    self._tracking_state = "searching"
            
            self._emit_status()
    
    async def process_tracking(self):
        """
        Process tracking and send PTZ commands.
        Should be called periodically (e.g., every 100ms).
        """
        if not self._running or self._tracking_state != "tracking":
            return
        
        if not self._last_bbox:
            return
        
        # Calculate target position as percentage of frame
        x, y, w, h = self._last_bbox
        target_x = (x + w / 2) / self.frame_width
        target_y = (y + h / 2) / self.frame_height
        
        # Apply smoothing
        self._smoothed_x = (
            self.config.smoothing_factor * target_x +
            (1 - self.config.smoothing_factor) * self._smoothed_x
        )
        self._smoothed_y = (
            self.config.smoothing_factor * target_y +
            (1 - self.config.smoothing_factor) * self._smoothed_y
        )
        
        # Calculate offset from center
        offset_x = self._smoothed_x - 0.5
        offset_y = self._smoothed_y - 0.5
        
        # Check if within deadzone
        deadzone_x = self.config.deadzone_x / 2
        deadzone_y = self.config.deadzone_y / 2
        
        need_move_x = abs(offset_x) > deadzone_x
        need_move_y = abs(offset_y) > deadzone_y
        
        if not need_move_x and not need_move_y:
            # Target is centered enough
            await ptz_manager.stop(self.camera_id)
            return
        
        # Determine speed based on offset
        def get_speed(offset: float, deadzone: float) -> int:
            excess = abs(offset) - deadzone
            if excess > 0.3:
                return self.config.fast_speed
            elif excess > 0.15:
                return self.config.medium_speed
            else:
                return self.config.slow_speed
        
        # Send PTZ commands
        if need_move_x:
            direction = "right" if offset_x > 0 else "left"
            speed = get_speed(offset_x, deadzone_x)
            await ptz_manager.move(self.camera_id, direction, speed)
        
        if need_move_y:
            direction = "down" if offset_y > 0 else "up"
            speed = get_speed(offset_y, deadzone_y)
            await ptz_manager.move(self.camera_id, direction, speed)
    
    def _emit_status(self):
        """Emit tracking status event"""
        status = TrackingStatus(
            active=self._running,
            target_name=self._target_name,
            tracking_state=self._tracking_state,
            bbox=self._last_bbox
        )
        
        event = create_tracking_event(self.camera_id, status)
        event_bus.publish_sync(event)
    
    def get_status(self) -> Dict:
        """Get current tracking status"""
        with self._lock:
            return {
                "camera_id": self.camera_id,
                "active": self._running,
                "target_name": self._target_name,
                "tracking_state": self._tracking_state,
                "bbox": self._last_bbox,
                "last_seen": self._last_seen.isoformat() if self._last_seen else None
            }


class TrackerManager:
    """
    Manages person trackers for multiple cameras.
    """
    
    _instance: Optional['TrackerManager'] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._trackers: Dict[str, PersonTracker] = {}
        self._tracking_loop_task: Optional[asyncio.Task] = None
        self._running = False
        self._initialized = True
        
        # Subscribe to face events
        event_bus.subscribe(EventType.FACES_DETECTED, self._on_faces_detected)
        
        logger.info("TrackerManager initialized")
    
    def get_tracker(self, camera_id: str) -> PersonTracker:
        """Get or create tracker for camera"""
        if camera_id not in self._trackers:
            self._trackers[camera_id] = PersonTracker(camera_id)
        return self._trackers[camera_id]
    
    def start_tracking(self, camera_id: str, target_name: str):
        """Start tracking person on camera"""
        tracker = self.get_tracker(camera_id)
        tracker.start_tracking(target_name)
    
    def stop_tracking(self, camera_id: str):
        """Stop tracking on camera"""
        tracker = self.get_tracker(camera_id)
        tracker.stop_tracking()
    
    def stop_all_tracking(self):
        """Stop all tracking"""
        for tracker in self._trackers.values():
            tracker.stop_tracking()
    
    def _on_faces_detected(self, event: Event):
        """Handle face detection events"""
        camera_id = event.camera_id
        faces_data = event.data.get("faces", [])
        
        faces = [
            FaceDetection(
                name=f["name"],
                confidence=f["confidence"],
                bbox=f["bbox"],
                known=f["known"]
            )
            for f in faces_data
        ]
        
        if camera_id in self._trackers:
            self._trackers[camera_id].update_faces(faces)
    
    async def start_tracking_loop(self, interval: float = 0.1):
        """Start the tracking processing loop"""
        self._running = True
        
        while self._running:
            for tracker in self._trackers.values():
                await tracker.process_tracking()
            
            await asyncio.sleep(interval)
    
    def stop_tracking_loop(self):
        """Stop the tracking processing loop"""
        self._running = False
    
    def get_all_status(self) -> List[Dict]:
        """Get status of all trackers"""
        return [t.get_status() for t in self._trackers.values()]


# Global tracker manager instance
tracker_manager = TrackerManager()

