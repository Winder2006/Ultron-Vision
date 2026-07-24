"""
Face Recognition - Detection, encoding, and matching against known faces
"""

import cv2
import numpy as np
import pickle
import logging
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

# Try to import face_recognition (requires dlib)
try:
    import face_recognition as fr
    FACE_RECOGNITION_AVAILABLE = True
except ImportError:
    fr = None
    FACE_RECOGNITION_AVAILABLE = False
    logging.warning("face_recognition not available - install with: pip install face_recognition")

from .events import (
    event_bus, FaceDetection, create_faces_event
)
from .camera import Frame

logger = logging.getLogger(__name__)


@dataclass
class FaceRecognitionConfig:
    model: str = "hog"  # "hog" (CPU dlib), "cnn" (GPU dlib), "insightface" (GPU onnxruntime)
    tolerance: float = 0.6
    min_face_size: int = 50
    encodings_path: str = "data/face_encodings.pkl"
    # insightface: ArcFace cosine similarity -> confidence anchors
    # (sim 0.35 -> conf 0.60, sim 0.55 -> conf 0.85; known iff conf >= 0.60)
    insightface_pack: str = "buffalo_l"
    insightface_det_size: int = 640


@dataclass
class EnrolledFace:
    name: str
    encodings: List[np.ndarray]
    image_paths: List[str]


class FaceRecognitionEngine:
    """
    Face detection and recognition using face_recognition library.
    Supports GPU acceleration via CUDA when using CNN model.
    """
    
    _instance: Optional['FaceRecognitionEngine'] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self.config = FaceRecognitionConfig()
        self._known_faces: Dict[str, EnrolledFace] = {}
        self._known_encodings: List[np.ndarray] = []
        self._known_names: List[str] = []
        self._lock = threading.Lock()
        self._current_faces: Dict[str, List[FaceDetection]] = {}  # camera_id -> faces
        self._insight_app = None

        self._initialized = True
        logger.info(f"FaceRecognitionEngine initialized with model: {self.config.model}")
    
    def configure(self, config: FaceRecognitionConfig):
        """Update configuration"""
        self.config = config
        logger.info(f"FaceRecognitionEngine configured: model={config.model}, tolerance={config.tolerance}")
    
    def _get_insightface(self):
        """Lazy-init InsightFace (RetinaFace det + ArcFace rec) on the GPU."""
        if self._insight_app is None:
            from insightface.app import FaceAnalysis  # heavy import, keep lazy

            app = FaceAnalysis(
                name=self.config.insightface_pack,
                providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
            )
            size = self.config.insightface_det_size
            app.prepare(ctx_id=0, det_size=(size, size))
            provider = app.models["recognition"].session.get_providers()[0]
            if provider != "CUDAExecutionProvider":
                logger.warning(
                    "InsightFace running on %s — install the Jetson "
                    "onnxruntime-gpu wheel for GPU inference", provider
                )
            logger.info(
                f"InsightFace ready (pack={self.config.insightface_pack}, "
                f"det={size}, provider={provider})"
            )
            self._insight_app = app
        return self._insight_app

    @staticmethod
    def _calibrate_sim(sim: float) -> float:
        """ArcFace cosine similarity -> confidence (0.35->0.60, 0.55->0.85)."""
        conf = 0.60 + (sim - 0.35) * (0.85 - 0.60) / (0.55 - 0.35)
        return max(0.0, min(0.99, conf))

    def _best_embedding_match(self, embedding: np.ndarray):
        """Best cosine match among enrolled ArcFace embeddings (skips any
        legacy dlib 128-d encodings that may share the pickle)."""
        best_name, best_sim = None, -1.0
        for enc, name in zip(self._known_encodings, self._known_names):
            if enc.shape != embedding.shape:
                continue
            sim = float(np.dot(enc, embedding))
            if sim > best_sim:
                best_name, best_sim = name, sim
        return best_name, best_sim

    def _recognize_insightface(self, image: np.ndarray) -> List[FaceDetection]:
        """Detect + recognize via InsightFace. Bboxes are full-res (the model
        letterboxes to det_size internally and maps coords back)."""
        detections: List[FaceDetection] = []
        for face in self._get_insightface().get(image):
            x1, y1, x2, y2 = [int(v) for v in face.bbox]
            w, h = x2 - x1, y2 - y1
            if min(w, h) < self.config.min_face_size:
                continue
            name, sim = self._best_embedding_match(face.normed_embedding)
            conf = self._calibrate_sim(sim)
            if name is not None and conf >= 0.60:
                detections.append(FaceDetection(
                    name=name, confidence=round(conf, 2),
                    bbox=[x1, y1, w, h], known=True
                ))
            else:
                detections.append(FaceDetection(
                    name="Unknown", confidence=0.0,
                    bbox=[x1, y1, w, h], known=False
                ))
        return detections

    def load_encodings(self, path: Optional[str] = None):
        """Load face encodings from file"""
        path = path or self.config.encodings_path
        encodings_file = Path(path)
        
        if not encodings_file.exists():
            logger.info("No encodings file found, starting with empty database")
            return
        
        try:
            with open(encodings_file, 'rb') as f:
                data = pickle.load(f)
            
            self._known_faces = data.get('faces', {})
            self._rebuild_encoding_lists()
            
            logger.info(f"Loaded {len(self._known_faces)} enrolled faces")
            
        except Exception as e:
            logger.error(f"Error loading encodings: {e}")
    
    def save_encodings(self, path: Optional[str] = None):
        """Save face encodings to file"""
        path = path or self.config.encodings_path
        encodings_file = Path(path)
        encodings_file.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            with open(encodings_file, 'wb') as f:
                pickle.dump({'faces': self._known_faces}, f)
            
            logger.info(f"Saved {len(self._known_faces)} face encodings")
            
        except Exception as e:
            logger.error(f"Error saving encodings: {e}")
    
    def _rebuild_encoding_lists(self):
        """Rebuild flat lists of encodings and names for faster matching"""
        self._known_encodings = []
        self._known_names = []
        
        for name, face in self._known_faces.items():
            for encoding in face.encodings:
                self._known_encodings.append(encoding)
                self._known_names.append(name)
    
    def enroll_face(
        self,
        name: str,
        image: np.ndarray,
        image_path: Optional[str] = None
    ) -> bool:
        """
        Enroll a new face or add encoding to existing person.
        Returns True if successful.
        """
        with self._lock:
            try:
                if self.config.model == "insightface":
                    faces = self._get_insightface().get(image)
                    if not faces:
                        logger.warning(f"No face found in image for {name}")
                        return False
                    if len(faces) > 1:
                        logger.warning(f"Multiple faces found, using largest for {name}")
                    face = max(
                        faces,
                        key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1])
                    )
                    encoding = face.normed_embedding.copy()
                else:
                    # Convert BGR to RGB for face_recognition
                    rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

                    # Detect faces
                    face_locations = fr.face_locations(
                        rgb_image,
                        model=self.config.model
                    )

                    if not face_locations:
                        logger.warning(f"No face found in image for {name}")
                        return False

                    if len(face_locations) > 1:
                        logger.warning(f"Multiple faces found, using largest for {name}")
                        # Use largest face
                        face_locations = [max(
                            face_locations,
                            key=lambda loc: (loc[2] - loc[0]) * (loc[1] - loc[3])
                        )]

                    # Generate encoding
                    encodings = fr.face_encodings(rgb_image, face_locations)

                    if not encodings:
                        logger.warning(f"Could not generate encoding for {name}")
                        return False

                    encoding = encodings[0]
                
                # Add to known faces
                if name in self._known_faces:
                    self._known_faces[name].encodings.append(encoding)
                    if image_path:
                        self._known_faces[name].image_paths.append(image_path)
                else:
                    self._known_faces[name] = EnrolledFace(
                        name=name,
                        encodings=[encoding],
                        image_paths=[image_path] if image_path else []
                    )
                
                self._rebuild_encoding_lists()
                self.save_encodings()
                
                logger.info(f"Enrolled face for {name}")
                return True
                
            except Exception as e:
                logger.error(f"Error enrolling face: {e}")
                return False
    
    def remove_face(self, name: str) -> bool:
        """Remove a person from the database"""
        with self._lock:
            if name in self._known_faces:
                del self._known_faces[name]
                self._rebuild_encoding_lists()
                self.save_encodings()
                logger.info(f"Removed face for {name}")
                return True
            return False
    
    def get_enrolled_names(self) -> List[str]:
        """Get list of all enrolled names"""
        return list(self._known_faces.keys())
    
    def get_enrolled_face(self, name: str) -> Optional[EnrolledFace]:
        """Get enrolled face data by name"""
        return self._known_faces.get(name)
    
    def detect_faces(
        self,
        image: np.ndarray,
        scale: float = 1.0
    ) -> List[Tuple[Tuple[int, int, int, int], Optional[np.ndarray]]]:
        """
        Detect faces in image.
        Returns list of (location, encoding) tuples.
        """
        if not FACE_RECOGNITION_AVAILABLE:
            # Fallback: use OpenCV cascade classifier for face detection only
            return self._detect_faces_opencv(image, scale)
        
        # Resize for faster processing if scale < 1
        if scale < 1.0:
            small_image = cv2.resize(image, (0, 0), fx=scale, fy=scale)
        else:
            small_image = image
        
        # Convert BGR to RGB
        rgb_image = cv2.cvtColor(small_image, cv2.COLOR_BGR2RGB)
        
        # Detect faces
        face_locations = fr.face_locations(
            rgb_image,
            model=self.config.model
        )
        
        # Filter by minimum size
        min_size = self.config.min_face_size * scale
        face_locations = [
            loc for loc in face_locations
            if (loc[2] - loc[0]) >= min_size and (loc[1] - loc[3]) >= min_size
        ]
        
        # Generate encodings
        face_encodings = fr.face_encodings(rgb_image, face_locations)
        
        # Scale locations back to original size
        if scale < 1.0:
            scale_factor = 1.0 / scale
            face_locations = [
                (
                    int(top * scale_factor),
                    int(right * scale_factor),
                    int(bottom * scale_factor),
                    int(left * scale_factor)
                )
                for top, right, bottom, left in face_locations
            ]
        
        return list(zip(face_locations, face_encodings))
    
    def _detect_faces_opencv(
        self,
        image: np.ndarray,
        scale: float = 1.0
    ) -> List[Tuple[Tuple[int, int, int, int], Optional[np.ndarray]]]:
        """
        Fallback face detection using OpenCV Haar cascade.
        No encoding/recognition - just detection.
        """
        # Load cascade classifier (cached)
        if not hasattr(self, '_cascade'):
            cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
            self._cascade = cv2.CascadeClassifier(cascade_path)
        
        # Resize for faster processing
        if scale < 1.0:
            small_image = cv2.resize(image, (0, 0), fx=scale, fy=scale)
        else:
            small_image = image
        
        # Convert to grayscale
        gray = cv2.cvtColor(small_image, cv2.COLOR_BGR2GRAY)
        
        # Detect faces
        faces = self._cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(self.config.min_face_size, self.config.min_face_size)
        )
        
        # Convert to face_recognition format (top, right, bottom, left)
        results = []
        scale_factor = 1.0 / scale if scale < 1.0 else 1.0
        
        for (x, y, w, h) in faces:
            top = int(y * scale_factor)
            right = int((x + w) * scale_factor)
            bottom = int((y + h) * scale_factor)
            left = int(x * scale_factor)
            results.append(((top, right, bottom, left), None))
        
        return results
    
    def recognize_faces(
        self,
        image: np.ndarray,
        scale: float = 0.5
    ) -> List[FaceDetection]:
        """
        Detect and recognize faces in image.
        Returns list of FaceDetection objects.
        """
        if self.config.model == "insightface":
            # InsightFace resizes internally (det_size); scale is ignored.
            return self._recognize_insightface(image)

        faces = self.detect_faces(image, scale)
        detections: List[FaceDetection] = []
        
        for location, encoding in faces:
            top, right, bottom, left = location
            bbox = [left, top, right - left, bottom - top]
            
            # Only compare against same-dimension (dlib 128-d) encodings —
            # ArcFace 512-d embeddings may share the pickle after a model switch.
            known = [
                (enc, nm) for enc, nm in
                zip(self._known_encodings, self._known_names)
                if encoding is not None and enc.shape == encoding.shape
            ]
            if known:
                known_encs = [enc for enc, _ in known]
                known_names = [nm for _, nm in known]
                # Compare against known faces
                distances = fr.face_distance(known_encs, encoding)
                
                if len(distances) > 0:
                    min_idx = np.argmin(distances)
                    min_distance = distances[min_idx]
                    
                    if min_distance <= self.config.tolerance:
                        name = known_names[min_idx]
                        confidence = 1.0 - min_distance
                        detections.append(FaceDetection(
                            name=name,
                            confidence=round(confidence, 2),
                            bbox=bbox,
                            known=True
                        ))
                    else:
                        detections.append(FaceDetection(
                            name="Unknown",
                            confidence=0.0,
                            bbox=bbox,
                            known=False
                        ))
                else:
                    detections.append(FaceDetection(
                        name="Unknown",
                        confidence=0.0,
                        bbox=bbox,
                        known=False
                    ))
            else:
                detections.append(FaceDetection(
                    name="Unknown",
                    confidence=0.0,
                    bbox=bbox,
                    known=False
                ))
        
        return detections
    
    def process_frame(
        self,
        frame: Frame,
        scale: float = 0.5,
        emit_event: bool = True
    ) -> List[FaceDetection]:
        """
        Process a frame for face recognition.
        Optionally emits event to event bus.
        """
        detections = self.recognize_faces(frame.image, scale)

        with self._lock:
            self._current_faces[frame.camera_id] = detections

        # Emit even when empty: consumers rely on zero-face frames to clear
        # state (UI overlays, activity person counts, recorder unknown-face
        # tracking). Suppressing them left stale faces everywhere.
        if emit_event:
            event = create_faces_event(
                camera_id=frame.camera_id,
                faces=detections,
                frame_id=frame.frame_id
            )
            event_bus.publish_sync(event)
        
        return detections
    
    def get_current_faces(
        self,
        camera_id: Optional[str] = None
    ) -> Dict[str, List[FaceDetection]]:
        """Get currently visible faces, optionally filtered by camera"""
        if camera_id:
            return {camera_id: self._current_faces.get(camera_id, [])}
        return self._current_faces.copy()
    
    def get_all_visible_faces(self) -> List[Dict]:
        """Get all visible faces across all cameras"""
        result = []
        for camera_id, faces in self._current_faces.items():
            for face in faces:
                result.append({
                    **face.to_dict(),
                    "camera_id": camera_id
                })
        return result


# Global face recognition engine instance
face_engine = FaceRecognitionEngine()

