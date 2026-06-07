"""
Motion Detection - Background subtraction and motion region detection
"""

import cv2
import numpy as np
import logging
from typing import List, Optional, Dict, Tuple
from dataclasses import dataclass, field
import threading

from .events import (
    event_bus, MotionRegion, create_motion_event
)
from .camera import Frame

logger = logging.getLogger(__name__)


@dataclass
class MotionZone:
    """Configurable region of interest for motion detection"""
    name: str
    points: List[Tuple[int, int]]  # Polygon points
    enabled: bool = True


@dataclass
class MotionConfig:
    sensitivity: int = 25  # Lower = more sensitive (threshold value)
    min_area: int = 500  # Minimum contour area to count as motion
    blur_size: int = 21  # Gaussian blur kernel size
    dilate_iterations: int = 2
    history: int = 500  # Background subtractor history length
    var_threshold: int = 16  # Background subtractor threshold
    detect_shadows: bool = False


class MotionDetector:
    """
    Detects motion in video frames using background subtraction.
    Supports configurable zones and sensitivity.
    """
    
    def __init__(self, camera_id: str, config: Optional[MotionConfig] = None):
        self.camera_id = camera_id
        self.config = config or MotionConfig()
        
        # Background subtractor
        self._bg_subtractor = cv2.createBackgroundSubtractorMOG2(
            history=self.config.history,
            varThreshold=self.config.var_threshold,
            detectShadows=self.config.detect_shadows
        )
        
        # Motion zones (polygons)
        self._zones: List[MotionZone] = []
        self._zone_masks: Dict[str, np.ndarray] = {}
        
        # State
        self._motion_detected = False
        self._motion_regions: List[MotionRegion] = []
        self._frame_size: Optional[Tuple[int, int]] = None
        self._lock = threading.Lock()
        
        logger.info(f"MotionDetector initialized for camera {camera_id}")
    
    def configure(self, config: MotionConfig):
        """Update configuration"""
        self.config = config
        self._bg_subtractor = cv2.createBackgroundSubtractorMOG2(
            history=config.history,
            varThreshold=config.var_threshold,
            detectShadows=config.detect_shadows
        )
        logger.info(f"MotionDetector reconfigured for camera {self.camera_id}")
    
    def add_zone(self, zone: MotionZone):
        """Add a motion detection zone"""
        self._zones.append(zone)
        self._rebuild_zone_masks()
        logger.info(f"Added motion zone '{zone.name}' for camera {self.camera_id}")
    
    def remove_zone(self, zone_name: str):
        """Remove a motion detection zone"""
        self._zones = [z for z in self._zones if z.name != zone_name]
        self._rebuild_zone_masks()
        logger.info(f"Removed motion zone '{zone_name}' from camera {self.camera_id}")
    
    def clear_zones(self):
        """Clear all motion zones"""
        self._zones.clear()
        self._zone_masks.clear()
    
    def _rebuild_zone_masks(self):
        """Rebuild zone masks when zones change"""
        if self._frame_size is None:
            return
        
        self._zone_masks.clear()
        height, width = self._frame_size
        
        for zone in self._zones:
            if zone.enabled:
                mask = np.zeros((height, width), dtype=np.uint8)
                points = np.array(zone.points, dtype=np.int32)
                cv2.fillPoly(mask, [points], 255)
                self._zone_masks[zone.name] = mask
    
    def detect(
        self,
        frame: Frame,
        emit_event: bool = True
    ) -> Tuple[bool, List[MotionRegion]]:
        """
        Detect motion in frame.
        Returns (motion_detected, list of motion regions).
        """
        with self._lock:
            image = frame.image
            height, width = image.shape[:2]
            
            # Update frame size and rebuild zone masks if needed
            if self._frame_size != (height, width):
                self._frame_size = (height, width)
                self._rebuild_zone_masks()
            
            # Convert to grayscale
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            
            # Apply Gaussian blur
            blurred = cv2.GaussianBlur(
                gray,
                (self.config.blur_size, self.config.blur_size),
                0
            )
            
            # Apply background subtraction
            fg_mask = self._bg_subtractor.apply(blurred)
            
            # Apply threshold
            _, thresh = cv2.threshold(
                fg_mask,
                self.config.sensitivity,
                255,
                cv2.THRESH_BINARY
            )
            
            # Dilate to fill gaps
            kernel = np.ones((5, 5), np.uint8)
            dilated = cv2.dilate(
                thresh,
                kernel,
                iterations=self.config.dilate_iterations
            )
            
            # Apply zone masks if defined
            if self._zone_masks:
                combined_mask = np.zeros_like(dilated)
                for zone_mask in self._zone_masks.values():
                    combined_mask = cv2.bitwise_or(combined_mask, zone_mask)
                dilated = cv2.bitwise_and(dilated, combined_mask)
            
            # Find contours
            contours, _ = cv2.findContours(
                dilated,
                cv2.RETR_EXTERNAL,
                cv2.CHAIN_APPROX_SIMPLE
            )
            
            # Filter by area and create motion regions
            motion_regions: List[MotionRegion] = []
            
            for contour in contours:
                area = cv2.contourArea(contour)
                
                if area >= self.config.min_area:
                    x, y, w, h = cv2.boundingRect(contour)
                    motion_regions.append(MotionRegion(
                        bbox=[x, y, w, h],
                        area=int(area)
                    ))
            
            # Update state
            self._motion_detected = len(motion_regions) > 0
            self._motion_regions = motion_regions
            
            # Emit event
            if emit_event:
                event = create_motion_event(
                    camera_id=self.camera_id,
                    motion_detected=self._motion_detected,
                    regions=motion_regions,
                    frame_id=frame.frame_id
                )
                event_bus.publish_sync(event)
            
            return self._motion_detected, motion_regions
    
    @property
    def motion_detected(self) -> bool:
        """Is motion currently detected?"""
        return self._motion_detected
    
    @property
    def motion_regions(self) -> List[MotionRegion]:
        """Get current motion regions"""
        return self._motion_regions.copy()
    
    def get_status(self) -> Dict:
        """Get current motion status"""
        return {
            "camera_id": self.camera_id,
            "motion_detected": self._motion_detected,
            "regions": [r.to_dict() for r in self._motion_regions],
            "zones": [{"name": z.name, "enabled": z.enabled} for z in self._zones]
        }


class MotionDetectorManager:
    """
    Manages motion detectors for multiple cameras.
    """
    
    _instance: Optional['MotionDetectorManager'] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._detectors: Dict[str, MotionDetector] = {}
        self._default_config = MotionConfig()
        self._initialized = True
        logger.info("MotionDetectorManager initialized")
    
    def set_default_config(self, config: MotionConfig):
        """Set default configuration for new detectors"""
        self._default_config = config
    
    def get_detector(self, camera_id: str) -> MotionDetector:
        """Get or create motion detector for camera"""
        if camera_id not in self._detectors:
            self._detectors[camera_id] = MotionDetector(
                camera_id,
                self._default_config
            )
        return self._detectors[camera_id]
    
    def remove_detector(self, camera_id: str):
        """Remove motion detector for camera"""
        if camera_id in self._detectors:
            del self._detectors[camera_id]
    
    def get_all_status(self) -> List[Dict]:
        """Get motion status for all cameras"""
        return [d.get_status() for d in self._detectors.values()]
    
    def detect(
        self,
        frame: Frame,
        emit_event: bool = True
    ) -> Tuple[bool, List[MotionRegion]]:
        """Detect motion using appropriate detector"""
        detector = self.get_detector(frame.camera_id)
        return detector.detect(frame, emit_event)


# Global motion detector manager instance
motion_manager = MotionDetectorManager()

