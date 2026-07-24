"""
Event Bus - Central event system for decoupling detection modules from API/UI
"""

import asyncio
import logging
import threading
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
import json

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    FRAME_METADATA = "frame_metadata"
    FACES_DETECTED = "faces_detected"
    MOTION_DETECTED = "motion_detected"
    ACTIVITY_ALERT = "activity_alert"
    TRACKING_STATUS = "tracking_status"
    SYSTEM_STATUS = "system_status"
    CAMERA_STATUS = "camera_status"
    RECORDING_EVENT = "recording_event"


@dataclass
class Event:
    type: EventType
    camera_id: Optional[str]
    timestamp: datetime
    data: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type.value,
            "camera_id": self.camera_id,
            "timestamp": self.timestamp.isoformat(),
            "data": self.data
        }
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict())


@dataclass
class FaceDetection:
    name: str
    confidence: float
    bbox: List[int]  # [x, y, width, height]
    known: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MotionRegion:
    bbox: List[int]  # [x, y, width, height]
    area: int
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ActivityAlert:
    alert_type: str  # loitering, unknown_person, quiet_hours_motion, person_count_change
    description: str
    severity: str  # low, medium, high
    faces: List[FaceDetection] = field(default_factory=list)
    snapshot_path: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "alert_type": self.alert_type,
            "description": self.description,
            "severity": self.severity,
            "faces": [f.to_dict() for f in self.faces],
            "snapshot_path": self.snapshot_path
        }


@dataclass
class TrackingStatus:
    active: bool
    target_name: Optional[str]
    tracking_state: str  # tracking, searching, lost, idle
    bbox: Optional[List[int]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CameraStatus:
    camera_id: str
    online: bool
    fps: float
    resolution: Optional[tuple] = None
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "camera_id": self.camera_id,
            "online": self.online,
            "fps": self.fps,
            "resolution": list(self.resolution) if self.resolution else None,
            "error": self.error
        }


class EventBus:
    """
    Lightweight in-process event bus for pub/sub pattern.
    Supports both sync and async subscribers.
    """
    
    _instance: Optional['EventBus'] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._subscribers: Dict[EventType, List[Callable]] = {
            event_type: [] for event_type in EventType
        }
        self._all_subscribers: List[Callable] = []
        self._event_history: List[Event] = []
        self._max_history = 1000
        # threading.Lock, NOT asyncio.Lock: publish() runs from multiple
        # threads/loops, and an asyncio.Lock binds to the first loop that
        # acquires it, permanently breaking every other caller.
        self._lock = threading.Lock()
        self._main_loop: Optional[asyncio.AbstractEventLoop] = None
        self._pending_tasks: set = set()
        self._initialized = True
        logger.info("EventBus initialized")

    def set_main_loop(self, loop: asyncio.AbstractEventLoop):
        """Register the server's event loop. Worker threads publish onto this
        loop so all subscribers run in one place."""
        self._main_loop = loop
    
    def subscribe(self, event_type: EventType, callback: Callable):
        """Subscribe to a specific event type"""
        if callback not in self._subscribers[event_type]:
            self._subscribers[event_type].append(callback)
            logger.debug(f"Subscriber added for {event_type.value}")
    
    def subscribe_all(self, callback: Callable):
        """Subscribe to all event types"""
        if callback not in self._all_subscribers:
            self._all_subscribers.append(callback)
            logger.debug("Subscriber added for all events")
    
    def unsubscribe(self, event_type: EventType, callback: Callable):
        """Unsubscribe from a specific event type"""
        if callback in self._subscribers[event_type]:
            self._subscribers[event_type].remove(callback)
            logger.debug(f"Subscriber removed for {event_type.value}")
    
    def unsubscribe_all(self, callback: Callable):
        """Unsubscribe from all events"""
        if callback in self._all_subscribers:
            self._all_subscribers.remove(callback)
            logger.debug("Subscriber removed from all events")
    
    async def publish(self, event: Event):
        """Publish an event to all subscribers"""
        with self._lock:
            # Store in history
            self._event_history.append(event)
            if len(self._event_history) > self._max_history:
                self._event_history = self._event_history[-self._max_history:]

        # Iterate over copies: subscribers can (un)subscribe while we await
        # (e.g. an /events WebSocket client disconnecting mid-publish).
        for callback in list(self._subscribers[event.type]):
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(event)
                else:
                    callback(event)
            except Exception as e:
                logger.error(f"Error in event subscriber: {e}")

        # Notify all-event subscribers
        for callback in list(self._all_subscribers):
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(event)
                else:
                    callback(event)
            except Exception as e:
                logger.error(f"Error in all-event subscriber: {e}")

    def publish_sync(self, event: Event):
        """Publish from sync code, on or off the event loop thread.

        Detection runs in a worker thread; publishes are routed onto the
        server's loop instead of spinning up a throwaway loop per event
        (which used to bind this bus to one loop and silently kill every
        publish from the other side).
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None:
            # Already on a loop thread: schedule, keeping a strong reference
            # so the task isn't garbage-collected mid-flight.
            task = loop.create_task(self.publish(event))
            self._pending_tasks.add(task)
            task.add_done_callback(self._pending_tasks.discard)
        elif self._main_loop is not None and self._main_loop.is_running():
            asyncio.run_coroutine_threadsafe(self.publish(event), self._main_loop)
        else:
            # No server loop (tests, CLI tools): run to completion inline.
            asyncio.run(self.publish(event))
    
    def get_recent_events(
        self,
        event_type: Optional[EventType] = None,
        camera_id: Optional[str] = None,
        limit: int = 100
    ) -> List[Event]:
        """Get recent events from history with optional filters"""
        events = self._event_history.copy()
        
        if event_type:
            events = [e for e in events if e.type == event_type]
        
        if camera_id:
            events = [e for e in events if e.camera_id == camera_id]
        
        return events[-limit:]
    
    def clear_history(self):
        """Clear event history"""
        self._event_history.clear()
        logger.info("Event history cleared")


# Convenience functions for creating and publishing events
def create_faces_event(
    camera_id: str,
    faces: List[FaceDetection],
    frame_id: Optional[int] = None
) -> Event:
    return Event(
        type=EventType.FACES_DETECTED,
        camera_id=camera_id,
        timestamp=datetime.now(),
        data={
            "faces": [f.to_dict() for f in faces],
            "frame_id": frame_id
        }
    )


def create_motion_event(
    camera_id: str,
    motion_detected: bool,
    regions: List[MotionRegion],
    frame_id: Optional[int] = None
) -> Event:
    return Event(
        type=EventType.MOTION_DETECTED,
        camera_id=camera_id,
        timestamp=datetime.now(),
        data={
            "motion_detected": motion_detected,
            "regions": [r.to_dict() for r in regions],
            "frame_id": frame_id
        }
    )


def create_activity_alert(
    camera_id: str,
    alert: ActivityAlert
) -> Event:
    return Event(
        type=EventType.ACTIVITY_ALERT,
        camera_id=camera_id,
        timestamp=datetime.now(),
        data=alert.to_dict()
    )


def create_tracking_event(
    camera_id: str,
    status: TrackingStatus
) -> Event:
    return Event(
        type=EventType.TRACKING_STATUS,
        camera_id=camera_id,
        timestamp=datetime.now(),
        data=status.to_dict()
    )


def create_camera_status_event(status: CameraStatus) -> Event:
    return Event(
        type=EventType.CAMERA_STATUS,
        camera_id=status.camera_id,
        timestamp=datetime.now(),
        data=status.to_dict()
    )


def create_system_status_event(
    online: bool,
    cameras: List[CameraStatus],
    uptime_seconds: float,
    gpu_available: bool = False,
    gpu_usage: Optional[float] = None,
    cpu_usage: Optional[float] = None
) -> Event:
    return Event(
        type=EventType.SYSTEM_STATUS,
        camera_id=None,
        timestamp=datetime.now(),
        data={
            "online": online,
            "cameras": [c.to_dict() for c in cameras],
            "uptime_seconds": uptime_seconds,
            "gpu_available": gpu_available,
            "gpu_usage": gpu_usage,
            "cpu_usage": cpu_usage
        }
    )


# Global event bus instance
event_bus = EventBus()

