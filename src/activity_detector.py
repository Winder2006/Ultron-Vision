"""
Activity Detector - Suspicious behavior detection and alerting
"""

import logging
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime, time as dt_time, timedelta
from collections import defaultdict, deque
import threading

from .events import (
    event_bus, EventType, Event, FaceDetection,
    ActivityAlert, create_activity_alert
)

logger = logging.getLogger(__name__)


@dataclass
class ActivityConfig:
    loitering_threshold_seconds: int = 60
    quiet_hours_start: str = "23:00"
    quiet_hours_end: str = "06:00"
    unknown_person_alert_cooldown: int = 30  # seconds
    person_count_change_threshold: int = 1


@dataclass
class PersonTracking:
    """Track a person's presence in camera view"""
    name: str
    camera_id: str
    first_seen: datetime
    last_seen: datetime
    bbox: List[int]
    known: bool
    stationary_since: Optional[datetime] = None
    last_bbox: Optional[List[int]] = None


class ActivityDetector:
    """
    Detects suspicious activities:
    - Loitering (person stationary too long)
    - Unknown person
    - Motion during quiet hours
    - Person count changes
    """
    
    _instance: Optional['ActivityDetector'] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self.config = ActivityConfig()
        
        # Track people by camera
        self._tracked_people: Dict[str, Dict[str, PersonTracking]] = defaultdict(dict)
        
        # Track person counts per camera
        self._person_counts: Dict[str, int] = defaultdict(int)
        
        # Alert cooldowns to prevent spam
        self._alert_cooldowns: Dict[str, datetime] = {}
        
        # Recent alerts for querying (bounded deque — no manual trimming needed)
        self._recent_alerts: deque = deque(maxlen=1000)
        
        self._lock = threading.Lock()
        self._initialized = True
        
        event_bus.subscribe(EventType.FACES_DETECTED, self._on_faces_detected)
        event_bus.subscribe(EventType.MOTION_DETECTED, self._on_motion_detected)

        logger.info("ActivityDetector initialized")
    
    def configure(self, config: ActivityConfig):
        """Update configuration"""
        self.config = config
        logger.info("ActivityDetector configured")
    
    def _parse_time(self, time_str: str) -> dt_time:
        """Parse time string to time object"""
        parts = time_str.split(":")
        return dt_time(int(parts[0]), int(parts[1]))
    
    def _is_quiet_hours(self) -> bool:
        """Check if current time is within quiet hours"""
        now = datetime.now().time()
        start = self._parse_time(self.config.quiet_hours_start)
        end = self._parse_time(self.config.quiet_hours_end)
        
        # Handle overnight quiet hours (e.g., 23:00 - 06:00)
        if start > end:
            return now >= start or now <= end
        else:
            return start <= now <= end
    
    def _can_alert(self, alert_key: str) -> bool:
        """Check if alert cooldown has expired"""
        if alert_key not in self._alert_cooldowns:
            return True
        
        cooldown_end = self._alert_cooldowns[alert_key]
        return datetime.now() >= cooldown_end
    
    def _set_alert_cooldown(self, alert_key: str, seconds: int):
        """Set alert cooldown"""
        self._alert_cooldowns[alert_key] = datetime.now() + timedelta(seconds=seconds)
    
    def _emit_alert(self, camera_id: str, alert: ActivityAlert):
        """Emit activity alert event"""
        event = create_activity_alert(camera_id, alert)
        event_bus.publish_sync(event)
        
        # Store in recent alerts
        alert_dict = {
            "camera_id": camera_id,
            "timestamp": datetime.now().isoformat(),
            **alert.to_dict()
        }
        
        with self._lock:
            self._recent_alerts.append(alert_dict)
        
        logger.info(f"Activity alert: {alert.alert_type} on camera {camera_id}")
    
    def _bbox_distance(self, bbox1: List[int], bbox2: List[int]) -> float:
        """Calculate distance between two bounding box centers"""
        cx1 = bbox1[0] + bbox1[2] / 2
        cy1 = bbox1[1] + bbox1[3] / 2
        cx2 = bbox2[0] + bbox2[2] / 2
        cy2 = bbox2[1] + bbox2[3] / 2
        return ((cx1 - cx2) ** 2 + (cy1 - cy2) ** 2) ** 0.5
    
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
        
        self._process_faces(camera_id, faces)
    
    def _process_faces(self, camera_id: str, faces: List[FaceDetection]):
        """Process detected faces for activity analysis"""
        now = datetime.now()
        
        with self._lock:
            tracked = self._tracked_people[camera_id]
            current_names: Set[str] = set()
            
            for face in faces:
                # Use name + bbox area as identifier for unknowns
                if face.known:
                    person_id = face.name
                else:
                    person_id = f"unknown_{face.bbox[2]}x{face.bbox[3]}"
                
                current_names.add(person_id)
                
                if person_id in tracked:
                    # Update existing tracking
                    person = tracked[person_id]
                    person.last_seen = now
                    person.bbox = face.bbox
                    
                    # Check for stationary (loitering)
                    if person.last_bbox:
                        distance = self._bbox_distance(face.bbox, person.last_bbox)
                        
                        # If barely moved, track as stationary
                        if distance < 50:  # pixels
                            if person.stationary_since is None:
                                person.stationary_since = now
                            else:
                                # Check loitering threshold
                                stationary_seconds = (now - person.stationary_since).total_seconds()
                                
                                if stationary_seconds >= self.config.loitering_threshold_seconds:
                                    alert_key = f"loitering_{camera_id}_{person_id}"
                                    
                                    if self._can_alert(alert_key):
                                        self._emit_alert(camera_id, ActivityAlert(
                                            alert_type="loitering",
                                            description=f"{'Unknown person' if not face.known else face.name} has been stationary for {int(stationary_seconds)} seconds",
                                            severity="medium",
                                            faces=[face]
                                        ))
                                        self._set_alert_cooldown(alert_key, 60)
                        else:
                            person.stationary_since = None
                    
                    person.last_bbox = face.bbox
                else:
                    # New person detected
                    tracked[person_id] = PersonTracking(
                        name=face.name,
                        camera_id=camera_id,
                        first_seen=now,
                        last_seen=now,
                        bbox=face.bbox,
                        known=face.known,
                        last_bbox=face.bbox
                    )
                    
                    # Alert for unknown person
                    if not face.known:
                        alert_key = f"unknown_{camera_id}"
                        
                        if self._can_alert(alert_key):
                            self._emit_alert(camera_id, ActivityAlert(
                                alert_type="unknown_person",
                                description="Unknown person detected",
                                severity="high",
                                faces=[face]
                            ))
                            self._set_alert_cooldown(
                                alert_key,
                                self.config.unknown_person_alert_cooldown
                            )
            
            # Check for person count change
            old_count = self._person_counts[camera_id]
            new_count = len(current_names)
            
            if abs(new_count - old_count) >= self.config.person_count_change_threshold:
                if new_count > old_count:
                    change_type = "entered"
                else:
                    change_type = "left"
                
                alert_key = f"count_{camera_id}"
                
                if self._can_alert(alert_key):
                    self._emit_alert(camera_id, ActivityAlert(
                        alert_type="person_count_change",
                        description=f"Person count changed from {old_count} to {new_count} (someone {change_type})",
                        severity="low",
                        faces=faces
                    ))
                    self._set_alert_cooldown(alert_key, 10)
            
            self._person_counts[camera_id] = new_count
            
            # Clean up old tracking entries
            expired_threshold = now - timedelta(seconds=5)
            expired = [
                pid for pid, p in tracked.items()
                if p.last_seen < expired_threshold
            ]
            for pid in expired:
                del tracked[pid]
    
    def _on_motion_detected(self, event: Event):
        """Handle motion detection events"""
        camera_id = event.camera_id
        motion_detected = event.data.get("motion_detected", False)
        
        if motion_detected and self._is_quiet_hours():
            alert_key = f"quiet_hours_{camera_id}"
            
            if self._can_alert(alert_key):
                self._emit_alert(camera_id, ActivityAlert(
                    alert_type="quiet_hours_motion",
                    description="Motion detected during quiet hours",
                    severity="high"
                ))
                self._set_alert_cooldown(alert_key, 60)
    
    def get_recent_alerts(
        self,
        camera_id: Optional[str] = None,
        alert_type: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 100
    ) -> List[Dict]:
        """Get recent activity alerts with optional filters"""
        with self._lock:
            alerts = list(self._recent_alerts)
        
        if camera_id:
            alerts = [a for a in alerts if a["camera_id"] == camera_id]
        
        if alert_type:
            alerts = [a for a in alerts if a["alert_type"] == alert_type]
        
        if since:
            since_str = since.isoformat()
            alerts = [a for a in alerts if a["timestamp"] >= since_str]
        
        return alerts[-limit:]
    
    def get_activity_log(self, hours: int = 24) -> List[Dict]:
        """Get activity log for the last N hours"""
        since = datetime.now() - timedelta(hours=hours)
        return self.get_recent_alerts(since=since)
    
    def get_tracked_people(
        self,
        camera_id: Optional[str] = None
    ) -> Dict[str, List[Dict]]:
        """Get currently tracked people"""
        with self._lock:
            if camera_id:
                tracked = self._tracked_people.get(camera_id, {})
                return {
                    camera_id: [
                        {
                            "name": p.name,
                            "known": p.known,
                            "first_seen": p.first_seen.isoformat(),
                            "last_seen": p.last_seen.isoformat(),
                            "bbox": p.bbox,
                            "stationary": p.stationary_since is not None
                        }
                        for p in tracked.values()
                    ]
                }
            else:
                result = {}
                for cam_id, tracked in self._tracked_people.items():
                    result[cam_id] = [
                        {
                            "name": p.name,
                            "known": p.known,
                            "first_seen": p.first_seen.isoformat(),
                            "last_seen": p.last_seen.isoformat(),
                            "bbox": p.bbox,
                            "stationary": p.stationary_since is not None
                        }
                        for p in tracked.values()
                    ]
                return result


# Global activity detector instance
activity_detector = ActivityDetector()

