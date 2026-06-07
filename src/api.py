"""
FastAPI Server - REST API and WebSocket endpoints for MOTHER integration
"""

import asyncio
import logging
import time
import base64
import json
import yaml
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .events import event_bus, EventType, Event, CameraStatus, create_system_status_event
from .camera import camera_manager, CameraConfig, CameraStream
from .face_recognition import face_engine, FaceRecognitionConfig
from .face_enrollment import face_enrollment
from .motion_detection import motion_manager, MotionConfig
from .activity_detector import activity_detector, ActivityConfig
from .ptz_control import ptz_manager
from .tracker import tracker_manager
from .recorder import recorder_manager, RecordingConfig

logger = logging.getLogger(__name__)

# Pydantic models for API
class PTZMoveRequest(BaseModel):
    camera_id: str
    direction: str
    speed: int = 25

class PTZTrackRequest(BaseModel):
    camera_id: str
    target: str

class StatusResponse(BaseModel):
    online: bool
    cameras: List[Dict]
    uptime_seconds: float
    gpu: Optional[Dict] = None

class FaceResponse(BaseModel):
    name: str
    confidence: float
    bbox: List[int]
    camera_id: str

# Global state
_start_time = time.time()
_config: Dict[str, Any] = {}


_gpu_info: Optional[Dict[str, Any]] = None


def detect_gpu() -> Dict[str, Any]:
    """Detect CUDA availability (dlib compiled with CUDA = GPU face recognition).

    Result is cached — GPU presence does not change at runtime.
    """
    global _gpu_info
    if _gpu_info is not None:
        return _gpu_info
    _gpu_info = _probe_gpu()
    return _gpu_info


def _probe_gpu() -> Dict[str, Any]:
    try:
        import dlib
        if getattr(dlib, "DLIB_USE_CUDA", False):
            num = dlib.cuda.get_num_devices()
            if num > 0:
                return {"available": True, "devices": num, "backend": "dlib-cuda"}
    except Exception:
        pass
    # Fallback: OpenCV CUDA build
    try:
        import cv2
        count = cv2.cuda.getCudaEnabledDeviceCount()
        if count > 0:
            return {"available": True, "devices": count, "backend": "opencv-cuda"}
    except Exception:
        pass
    return {"available": False}


def load_config(config_path: str = "config.yaml") -> Dict:
    """Load configuration from YAML file"""
    global _config
    
    config_file = Path(config_path)
    
    if config_file.exists():
        with open(config_file) as f:
            _config = yaml.safe_load(f)
    else:
        logger.warning(f"Config file not found: {config_path}, using defaults")
        _config = {
            "cameras": [],
            "face_recognition": {"model": "hog", "tolerance": 0.6, "min_face_size": 50},
            "motion_detection": {"sensitivity": 25, "min_area": 500},
            "recording": {"enabled": True, "path": "data/recordings", "max_days": 14, "event_buffer_seconds": 30},
            "activity": {"loitering_threshold_seconds": 60, "quiet_hours_start": "23:00", "quiet_hours_end": "06:00"},
            "api": {"host": "0.0.0.0", "port": 8200},
            "ui": {"default_view": "cameras", "theme": "dark", "max_cameras_per_row": 3}
        }
    
    return _config


def initialize_system():
    """Initialize all system components from config"""
    global _config
    
    # Configure face recognition
    fr_config = _config.get("face_recognition", {})
    face_engine.configure(FaceRecognitionConfig(
        model=fr_config.get("model", "hog"),
        tolerance=fr_config.get("tolerance", 0.6),
        min_face_size=fr_config.get("min_face_size", 50)
    ))
    face_engine.load_encodings()
    
    # Configure motion detection
    md_config = _config.get("motion_detection", {})
    motion_manager.set_default_config(MotionConfig(
        sensitivity=md_config.get("sensitivity", 25),
        min_area=md_config.get("min_area", 500)
    ))
    
    # Configure activity detector
    act_config = _config.get("activity", {})
    activity_detector.configure(ActivityConfig(
        loitering_threshold_seconds=act_config.get("loitering_threshold_seconds", 60),
        quiet_hours_start=act_config.get("quiet_hours_start", "23:00"),
        quiet_hours_end=act_config.get("quiet_hours_end", "06:00")
    ))
    
    # Configure recorder
    rec_config = _config.get("recording", {})
    recorder_manager.configure(RecordingConfig(
        enabled=rec_config.get("enabled", True),
        path=rec_config.get("path", "data/recordings"),
        max_days=rec_config.get("max_days", 14),
        event_buffer_seconds=rec_config.get("event_buffer_seconds", 30)
    ))
    
    # Add cameras
    for cam_config in _config.get("cameras", []):
        camera = camera_manager.add_camera(CameraConfig(
            id=cam_config["id"],
            name=cam_config["name"],
            rtsp_url=cam_config["rtsp_url"],
            ptz_enabled=cam_config.get("ptz_enabled", False),
            api_url=cam_config.get("api_url")
        ))
        
        # Add PTZ controller if enabled
        if cam_config.get("ptz_enabled") and cam_config.get("api_url"):
            ptz_manager.add_controller(
                camera_id=cam_config["id"],
                api_url=cam_config["api_url"],
                username="admin",
                password=""  # From RTSP URL
            )
        
        # Add frame callback for processing
        camera.add_frame_callback(process_frame)
    
    logger.info("System initialized")


def process_frame(frame):
    """Process frame through all detection pipelines"""
    try:
        # Face recognition (every 5th frame for performance)
        if frame.frame_id % 5 == 0:
            face_engine.process_frame(frame, scale=0.5)
        
        # Motion detection (every 2nd frame)
        if frame.frame_id % 2 == 0:
            motion_manager.detect(frame)
        
        # Add to recorder
        recorder_manager.add_frame(frame)
        
    except Exception as e:
        logger.error(f"Error processing frame: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler"""
    # Startup
    logger.info("Starting ULTRON VISION API...")
    load_config()
    initialize_system()
    
    # Start cameras
    camera_manager.start_all()
    
    # Start recorder
    if _config.get("recording", {}).get("enabled", True):
        recorder_manager.start_all()
    
    # Start tracking loop
    asyncio.create_task(tracker_manager.start_tracking_loop())
    
    # Start system status broadcast
    asyncio.create_task(broadcast_system_status())
    
    logger.info("ULTRON VISION API started")
    
    yield
    
    # Shutdown
    logger.info("Shutting down ULTRON VISION API...")
    camera_manager.stop_all()
    recorder_manager.stop_all()
    tracker_manager.stop_tracking_loop()
    logger.info("ULTRON VISION API stopped")


# Create FastAPI app
app = FastAPI(
    title="ULTRON VISION",
    description="AI Camera Surveillance System",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# WebSocket connections for events
event_connections: List[WebSocket] = []
stream_connections: Dict[str, List[WebSocket]] = {}


async def broadcast_system_status():
    """Periodically broadcast system status"""
    while True:
        try:
            statuses = camera_manager.get_statuses()
            
            event = create_system_status_event(
                online=True,
                cameras=statuses,
                uptime_seconds=time.time() - _start_time,
                gpu_available=detect_gpu().get("available", False)
            )
            
            await event_bus.publish(event)
            
        except Exception as e:
            logger.error(f"Error broadcasting status: {e}")
        
        await asyncio.sleep(5)


# ==================== Status Endpoints ====================

@app.get("/status")
async def get_status() -> Dict:
    """Get system status"""
    statuses = camera_manager.get_statuses()
    
    return {
        "online": True,
        "cameras": [s.to_dict() for s in statuses],
        "uptime_seconds": time.time() - _start_time,
        "gpu": detect_gpu()
    }

@app.get("/health")
async def health_check() -> Dict:
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


# ==================== Live View Endpoints ====================

@app.get("/snapshot")
async def get_snapshot(camera_id: Optional[str] = None) -> Response:
    """Get current frame as JPEG"""
    if camera_id is None:
        cameras = list(camera_manager.get_all_cameras().keys())
        if cameras:
            camera_id = cameras[0]
        else:
            raise HTTPException(status_code=404, detail="No cameras configured")
    
    camera = camera_manager.get_camera(camera_id)
    
    if not camera:
        raise HTTPException(status_code=404, detail=f"Camera {camera_id} not found")
    
    jpeg = camera.get_latest_jpeg()
    
    if not jpeg:
        raise HTTPException(status_code=503, detail="No frame available")
    
    return Response(content=jpeg, media_type="image/jpeg")

@app.get("/snapshot/{camera_id}")
async def get_camera_snapshot(camera_id: str) -> Response:
    """Get snapshot from specific camera"""
    return await get_snapshot(camera_id)


@app.websocket("/stream/{camera_id}")
async def stream_camera(websocket: WebSocket, camera_id: str):
    """WebSocket stream of JPEG frames"""
    try:
        await websocket.accept()
    except Exception as e:
        logger.error(f"Failed to accept stream WebSocket: {e}")
        return
    
    camera = camera_manager.get_camera(camera_id)
    
    if not camera:
        await websocket.close(code=4004, reason=f"Camera {camera_id} not found")
        return
    
    # Add to connections
    if camera_id not in stream_connections:
        stream_connections[camera_id] = []
    stream_connections[camera_id].append(websocket)
    
    logger.info(f"Stream client connected for camera {camera_id}")
    
    try:
        last_frame_id = 0
        
        while True:
            try:
                frame = camera.get_latest_frame()
                
                if frame and frame.frame_id != last_frame_id:
                    last_frame_id = frame.frame_id
                    
                    # Send as base64 encoded JSON
                    jpeg = frame.to_jpeg(quality=70)
                    message = {
                        "type": "frame",
                        "timestamp": frame.timestamp.isoformat(),
                        "frame_id": frame.frame_id,
                        "data": base64.b64encode(jpeg).decode()
                    }
                    
                    await websocket.send_json(message)
                
                await asyncio.sleep(0.066)  # ~15 FPS
            except Exception as e:
                logger.debug(f"Stream frame error: {e}")
                break
            
    except WebSocketDisconnect:
        logger.info(f"Stream client disconnected for camera {camera_id}")
    except Exception as e:
        logger.error(f"Stream error: {e}")
    finally:
        if camera_id in stream_connections and websocket in stream_connections[camera_id]:
            stream_connections[camera_id].remove(websocket)


# ==================== Events WebSocket ====================

@app.websocket("/events")
async def events_websocket(websocket: WebSocket):
    """WebSocket for real-time events"""
    try:
        await websocket.accept()
    except Exception as e:
        logger.error(f"Failed to accept WebSocket: {e}")
        return
    
    event_connections.append(websocket)
    logger.info("Events WebSocket client connected")
    
    # Queue for events
    event_queue: asyncio.Queue = asyncio.Queue()
    
    # Event handler - put events in queue
    def queue_event(event: Event):
        try:
            event_queue.put_nowait(event)
        except:
            pass
    
    # Subscribe to all events
    event_bus.subscribe_all(queue_event)
    
    try:
        while True:
            try:
                # Wait for event with timeout to allow checking connection
                event = await asyncio.wait_for(event_queue.get(), timeout=1.0)
                await websocket.send_json(event.to_dict())
            except asyncio.TimeoutError:
                # Send ping to keep connection alive
                try:
                    await websocket.send_json({"type": "ping"})
                except:
                    break
            except Exception as e:
                logger.debug(f"Event send error: {e}")
                break
            
    except WebSocketDisconnect:
        logger.info("Events WebSocket client disconnected")
    except Exception as e:
        logger.error(f"Events WebSocket error: {e}")
    finally:
        event_bus.unsubscribe_all(queue_event)
        if websocket in event_connections:
            event_connections.remove(websocket)


# ==================== Face Recognition Endpoints ====================

@app.get("/faces")
async def get_visible_faces() -> List[Dict]:
    """Get currently visible faces"""
    return face_engine.get_all_visible_faces()

@app.get("/faces/unknown")
async def get_unknown_faces() -> List[Dict]:
    """Get unknown faces currently visible"""
    all_faces = face_engine.get_all_visible_faces()
    return [f for f in all_faces if not f.get("known", True)]

@app.post("/faces/enroll")
async def enroll_face(
    name: str = Form(...),
    image: UploadFile = File(...)
) -> Dict:
    """Enroll new face from uploaded image"""
    contents = await image.read()
    
    result = face_enrollment.enroll_from_bytes(
        name=name,
        image_bytes=contents,
        filename=image.filename
    )
    
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error", "Enrollment failed"))
    
    return result

@app.get("/faces/enrolled")
async def get_enrolled_faces() -> List[Dict]:
    """Get list of all enrolled people"""
    return face_enrollment.list_enrolled()

@app.delete("/faces/{name}")
async def delete_enrolled_face(name: str) -> Dict:
    """Remove enrolled face"""
    result = face_enrollment.remove_person(name)
    
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result.get("error", "Not found"))
    
    return result


# ==================== Motion and Activity Endpoints ====================

@app.get("/motion")
async def get_motion_status() -> List[Dict]:
    """Get current motion status per camera"""
    return motion_manager.get_all_status()

@app.get("/activity/alerts")
async def get_activity_alerts(
    camera_id: Optional[str] = Query(None),
    alert_type: Optional[str] = Query(None),
    hours: int = Query(24)
) -> List[Dict]:
    """Get recent activity alerts"""
    since = datetime.now() - timedelta(hours=hours)
    return activity_detector.get_recent_alerts(
        camera_id=camera_id,
        alert_type=alert_type,
        since=since
    )

@app.get("/activity/log")
async def get_activity_log(hours: int = Query(24)) -> List[Dict]:
    """Get activity log"""
    return activity_detector.get_activity_log(hours=hours)


# ==================== PTZ Control Endpoints ====================

@app.post("/ptz/move")
async def ptz_move(request: PTZMoveRequest) -> Dict:
    """Move PTZ camera"""
    if not ptz_manager.has_ptz(request.camera_id):
        raise HTTPException(status_code=400, detail="Camera does not support PTZ")
    
    success = await ptz_manager.move(
        camera_id=request.camera_id,
        direction=request.direction,
        speed=request.speed
    )
    
    return {"success": success}

@app.post("/ptz/preset/{preset_id}")
async def ptz_goto_preset(
    preset_id: int,
    camera_id: str = Query(...)
) -> Dict:
    """Go to PTZ preset position"""
    success = await ptz_manager.go_to_preset(camera_id, preset_id)
    return {"success": success}

@app.post("/ptz/track")
async def ptz_track(request: PTZTrackRequest) -> Dict:
    """Start tracking a person"""
    tracker_manager.start_tracking(request.camera_id, request.target)
    return {"success": True, "tracking": request.target}

@app.post("/ptz/stop")
async def ptz_stop_tracking(camera_id: str = Query(...)) -> Dict:
    """Stop PTZ tracking"""
    tracker_manager.stop_tracking(camera_id)
    await ptz_manager.stop(camera_id)
    return {"success": True}


# ==================== Recording Endpoints ====================

@app.get("/recordings")
async def get_recordings(
    camera_id: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    hours: int = Query(24)
) -> List[Dict]:
    """List recordings"""
    since = datetime.now() - timedelta(hours=hours)
    recordings = recorder_manager.get_all_recordings(
        camera_id=camera_id,
        recording_type=type,
        since=since
    )
    return [r.to_dict() for r in recordings]

@app.get("/recordings/{recording_id}")
async def download_recording(recording_id: str) -> FileResponse:
    """Download recording file"""
    recordings = recorder_manager.get_all_recordings()
    
    for recording in recordings:
        if recording.id == recording_id:
            file_path = Path(recording.file_path)
            if file_path.exists():
                return FileResponse(
                    path=file_path,
                    filename=file_path.name,
                    media_type="video/mp4"
                )
    
    raise HTTPException(status_code=404, detail="Recording not found")

@app.post("/snapshot/save")
async def save_snapshot(camera_id: str = Query(...)) -> Dict:
    """Take and save snapshot"""
    snapshot = recorder_manager.take_snapshot(camera_id)
    
    if not snapshot:
        raise HTTPException(status_code=500, detail="Failed to capture snapshot")
    
    return snapshot.to_dict()


# ==================== Crew Manifest Endpoints ====================

@app.get("/crew")
async def get_crew() -> List[Dict]:
    """Get everyone currently visible"""
    all_faces = face_engine.get_all_visible_faces()
    
    # Group by person
    crew = {}
    for face in all_faces:
        name = face["name"]
        if name not in crew:
            crew[name] = {
                "name": name,
                "known": face["known"],
                "cameras": [],
                "confidence": face["confidence"]
            }
        crew[name]["cameras"].append(face["camera_id"])
    
    return list(crew.values())

@app.get("/crew/history")
async def get_crew_history(hours: int = Query(24)) -> List[Dict]:
    """Get entry/exit log"""
    # Get tracked people history from activity detector
    return activity_detector.get_activity_log(hours=hours)

@app.get("/crew/{name}/last_seen")
async def get_last_seen(name: str) -> Dict:
    """When was person last seen?"""
    tracked = activity_detector.get_tracked_people()
    
    for camera_id, people in tracked.items():
        for person in people:
            if person["name"] == name:
                return {
                    "name": name,
                    "camera_id": camera_id,
                    "last_seen": person["last_seen"],
                    "currently_visible": True
                }
    
    # Check event history
    events = event_bus.get_recent_events(event_type=EventType.FACES_DETECTED, limit=1000)
    
    for event in reversed(events):
        faces = event.data.get("faces", [])
        for face in faces:
            if face["name"] == name:
                return {
                    "name": name,
                    "camera_id": event.camera_id,
                    "last_seen": event.timestamp.isoformat(),
                    "currently_visible": False
                }
    
    raise HTTPException(status_code=404, detail=f"Person {name} not found")


# ==================== UI Config Endpoint ====================

@app.get("/ui/config")
async def get_ui_config() -> Dict:
    """Get UI configuration"""
    cameras = []
    
    for cam_id, config in camera_manager.get_all_configs().items():
        cameras.append({
            "id": config.id,
            "name": config.name,
            "ptz_enabled": config.ptz_enabled
        })
    
    ui_config = _config.get("ui", {})
    
    return {
        "cameras": cameras,
        "default_view": ui_config.get("default_view", "cameras"),
        "theme": ui_config.get("theme", "dark"),
        "max_cameras_per_row": ui_config.get("max_cameras_per_row", 3)
    }


# Serve static files for built frontend
web_dist = Path(__file__).parent.parent / "web" / "dist"
if web_dist.exists():
    app.mount("/", StaticFiles(directory=str(web_dist), html=True), name="static")


def run_server():
    """Run the API server"""
    import uvicorn
    
    load_config()
    api_config = _config.get("api", {})
    
    uvicorn.run(
        "src.api:app",
        host=api_config.get("host", "0.0.0.0"),
        port=api_config.get("port", 8200),
        reload=False,
        log_level="info"
    )


if __name__ == "__main__":
    run_server()

