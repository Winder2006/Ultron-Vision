"""
Face Enrollment - Add new faces to the recognition database
"""

import cv2
import numpy as np
import logging
from pathlib import Path
from typing import Optional, List, Dict
from datetime import datetime
import shutil

from .face_recognition import face_engine, FACE_RECOGNITION_AVAILABLE
from .camera import camera_manager, Frame

logger = logging.getLogger(__name__)


class FaceEnrollment:
    """
    Handles face enrollment via CLI, API, and live stream capture.
    """
    
    def __init__(self, known_faces_dir: str = "data/known_faces"):
        self.known_faces_dir = Path(known_faces_dir)
        self.known_faces_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"FaceEnrollment initialized with directory: {known_faces_dir}")
    
    def enroll_from_file(
        self,
        name: str,
        image_path: str
    ) -> Dict[str, any]:
        """
        Enroll a face from an image file.
        Returns status dict.
        """
        if not FACE_RECOGNITION_AVAILABLE:
            return {"success": False, "error": "face_recognition library not installed. Install with: pip install face_recognition"}
        
        try:
            image_file = Path(image_path)
            
            if not image_file.exists():
                return {"success": False, "error": "Image file not found"}
            
            # Read image
            image = cv2.imread(str(image_file))
            
            if image is None:
                return {"success": False, "error": "Could not read image file"}
            
            # Create person directory
            person_dir = self.known_faces_dir / name
            person_dir.mkdir(exist_ok=True)
            
            # Copy image to known_faces
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            dest_path = person_dir / f"{timestamp}{image_file.suffix}"
            shutil.copy(image_file, dest_path)
            
            # Enroll in face engine
            success = face_engine.enroll_face(
                name=name,
                image=image,
                image_path=str(dest_path)
            )
            
            if success:
                return {
                    "success": True,
                    "name": name,
                    "image_path": str(dest_path)
                }
            else:
                # Clean up copied file
                dest_path.unlink(missing_ok=True)
                return {"success": False, "error": "No face detected in image"}
                
        except Exception as e:
            logger.error(f"Error enrolling from file: {e}")
            return {"success": False, "error": str(e)}
    
    def enroll_from_bytes(
        self,
        name: str,
        image_bytes: bytes,
        filename: str = "uploaded.jpg"
    ) -> Dict[str, any]:
        """
        Enroll a face from image bytes (e.g., from API upload).
        """
        if not FACE_RECOGNITION_AVAILABLE:
            return {"success": False, "error": "face_recognition library not installed. Install with: pip install face_recognition"}
        
        try:
            # Decode image
            nparr = np.frombuffer(image_bytes, np.uint8)
            image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
            if image is None:
                return {"success": False, "error": "Could not decode image"}
            
            # Create person directory
            person_dir = self.known_faces_dir / name
            person_dir.mkdir(exist_ok=True)
            
            # Save image
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            ext = Path(filename).suffix or ".jpg"
            dest_path = person_dir / f"{timestamp}{ext}"
            cv2.imwrite(str(dest_path), image)
            
            # Enroll in face engine
            success = face_engine.enroll_face(
                name=name,
                image=image,
                image_path=str(dest_path)
            )
            
            if success:
                return {
                    "success": True,
                    "name": name,
                    "image_path": str(dest_path)
                }
            else:
                dest_path.unlink(missing_ok=True)
                return {"success": False, "error": "No face detected in image"}
                
        except Exception as e:
            logger.error(f"Error enrolling from bytes: {e}")
            return {"success": False, "error": str(e)}
    
    def enroll_from_camera(
        self,
        name: str,
        camera_id: str,
        num_samples: int = 3
    ) -> Dict[str, any]:
        """
        Capture and enroll face from live camera stream.
        Takes multiple samples for better recognition.
        """
        try:
            camera = camera_manager.get_camera(camera_id)
            
            if not camera:
                return {"success": False, "error": f"Camera {camera_id} not found"}
            
            if not camera.is_connected:
                return {"success": False, "error": f"Camera {camera_id} not connected"}
            
            # Create person directory
            person_dir = self.known_faces_dir / name
            person_dir.mkdir(exist_ok=True)
            
            enrolled_count = 0
            image_paths = []
            
            for i in range(num_samples):
                # Get frame from camera
                frame = camera.get_latest_frame()
                
                if frame is None:
                    continue
                
                # Save image
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                dest_path = person_dir / f"{timestamp}.jpg"
                cv2.imwrite(str(dest_path), frame.image)
                
                # Try to enroll
                success = face_engine.enroll_face(
                    name=name,
                    image=frame.image,
                    image_path=str(dest_path)
                )
                
                if success:
                    enrolled_count += 1
                    image_paths.append(str(dest_path))
                else:
                    dest_path.unlink(missing_ok=True)
            
            if enrolled_count > 0:
                return {
                    "success": True,
                    "name": name,
                    "samples_enrolled": enrolled_count,
                    "image_paths": image_paths
                }
            else:
                return {"success": False, "error": "No faces detected in camera frames"}
                
        except Exception as e:
            logger.error(f"Error enrolling from camera: {e}")
            return {"success": False, "error": str(e)}
    
    def remove_person(self, name: str) -> Dict[str, any]:
        """
        Remove a person and their images from the database.
        """
        try:
            # Remove from face engine
            success = face_engine.remove_face(name)
            
            # Remove image directory
            person_dir = self.known_faces_dir / name
            if person_dir.exists():
                shutil.rmtree(person_dir)
            
            if success:
                return {"success": True, "name": name}
            else:
                return {"success": False, "error": f"Person {name} not found"}
                
        except Exception as e:
            logger.error(f"Error removing person: {e}")
            return {"success": False, "error": str(e)}
    
    def list_enrolled(self) -> List[Dict]:
        """
        List all enrolled people with their image counts.
        """
        enrolled = []
        
        for name in face_engine.get_enrolled_names():
            face_data = face_engine.get_enrolled_face(name)
            person_dir = self.known_faces_dir / name
            
            image_count = len(list(person_dir.glob("*"))) if person_dir.exists() else 0
            
            enrolled.append({
                "name": name,
                "encoding_count": len(face_data.encodings) if face_data else 0,
                "image_count": image_count,
                "image_paths": face_data.image_paths if face_data else []
            })
        
        return enrolled
    
    def get_person_images(self, name: str) -> List[str]:
        """
        Get list of image paths for a person.
        """
        person_dir = self.known_faces_dir / name
        
        if not person_dir.exists():
            return []
        
        return [str(p) for p in person_dir.glob("*") if p.is_file()]


# Global enrollment instance
face_enrollment = FaceEnrollment()


def cli_enroll():
    """
    CLI interface for face enrollment.
    """
    import argparse
    
    parser = argparse.ArgumentParser(description="Face Enrollment CLI")
    subparsers = parser.add_subparsers(dest="command")
    
    # Enroll from file
    enroll_parser = subparsers.add_parser("enroll", help="Enroll face from image file")
    enroll_parser.add_argument("name", help="Person's name")
    enroll_parser.add_argument("image", help="Path to image file")
    
    # List enrolled
    subparsers.add_parser("list", help="List enrolled people")
    
    # Remove person
    remove_parser = subparsers.add_parser("remove", help="Remove enrolled person")
    remove_parser.add_argument("name", help="Person's name to remove")
    
    args = parser.parse_args()
    
    # Initialize face engine
    face_engine.load_encodings()
    
    if args.command == "enroll":
        result = face_enrollment.enroll_from_file(args.name, args.image)
        print(result)
    elif args.command == "list":
        enrolled = face_enrollment.list_enrolled()
        for person in enrolled:
            print(f"  {person['name']}: {person['encoding_count']} encodings, {person['image_count']} images")
    elif args.command == "remove":
        result = face_enrollment.remove_person(args.name)
        print(result)
    else:
        parser.print_help()


if __name__ == "__main__":
    cli_enroll()

