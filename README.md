# MOTHER VISION

AI-powered camera surveillance system with facial recognition, motion detection, and real-time alerts. Designed to integrate with the MOTHER voice assistant.

![MOTHER VISION](https://img.shields.io/badge/MOTHER-VISION-00ff7f?style=for-the-badge&labelColor=0a0f0d)

## Features

- 🎥 **Multi-Camera Support** - Connect multiple IP cameras via RTSP
- 👤 **Facial Recognition** - Detect and identify known people with GPU acceleration
- 🚶 **Motion Detection** - Configurable zones and sensitivity
- ⚠️ **Activity Alerts** - Detect loitering, unknown persons, and quiet hours violations
- 🎯 **PTZ Control** - Pan, tilt, zoom with person tracking
- 📹 **Recording** - Continuous and event-triggered video clips
- 🌐 **REST API** - Full API for MOTHER voice assistant integration
- 🖥️ **Real-time Dashboard** - Modern web UI with live video and overlays

## Quick Start

### Prerequisites

- Python 3.10+
- Node.js 18+
- NVIDIA GPU (optional, for faster face recognition)
- Reolink E1 Pro camera(s) or compatible RTSP cameras

### Installation

1. **Clone and setup Python environment:**

```bash
cd "MOTHER VISION"
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/Mac

pip install -r requirements.txt
```

2. **Install dlib with CUDA (optional for GPU):**

```bash
# For GPU acceleration, install dlib with CUDA support
pip install dlib --no-cache-dir
```

3. **Configure cameras:**

Edit `config.yaml` with your camera details:

```yaml
cameras:
  - id: "front_door"
    name: "Front Door"
    rtsp_url: "rtsp://admin:YOUR_PASSWORD@192.168.1.100:554/h264Preview_01_main"
    ptz_enabled: true
    api_url: "http://192.168.1.100"
```

4. **Start the backend:**

```bash
python main.py
```

The API will be available at `http://localhost:8200`

5. **Setup the frontend (optional):**

```bash
cd web
npm install
npm run dev
```

The dashboard will be available at `http://localhost:3000`

## Configuration

### config.yaml

```yaml
cameras:
  - id: "front_door"
    name: "Front Door"
    rtsp_url: "rtsp://admin:password@192.168.1.100:554/h264Preview_01_main"
    ptz_enabled: true
    api_url: "http://192.168.1.100"

face_recognition:
  model: "hog"          # "hog" for CPU, "cnn" for GPU
  tolerance: 0.6        # Lower = stricter matching
  min_face_size: 50     # Minimum face size in pixels

motion_detection:
  sensitivity: 25       # Lower = more sensitive
  min_area: 500         # Minimum motion area

recording:
  enabled: true
  path: "data/recordings"
  max_days: 14
  event_buffer_seconds: 30

activity:
  loitering_threshold_seconds: 60
  quiet_hours_start: "23:00"
  quiet_hours_end: "06:00"

api:
  host: "0.0.0.0"
  port: 8200

ui:
  theme: "dark"
  max_cameras_per_row: 3
```

## API Reference

### Status

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/status` | GET | System status and camera info |
| `/health` | GET | Health check |

### Live View

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/snapshot` | GET | Current frame from default camera |
| `/snapshot/{camera_id}` | GET | Snapshot from specific camera |
| `WS /stream/{camera_id}` | WebSocket | Live JPEG stream |
| `WS /events` | WebSocket | Real-time event stream |

### Face Recognition

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/faces` | GET | Currently visible faces |
| `/faces/unknown` | GET | Unknown faces currently visible |
| `/faces/enroll` | POST | Enroll new face (multipart) |
| `/faces/enrolled` | GET | List enrolled people |
| `/faces/{name}` | DELETE | Remove enrolled face |

### Motion & Activity

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/motion` | GET | Motion status per camera |
| `/activity/alerts` | GET | Activity alerts (filterable) |
| `/activity/log` | GET | Activity log (last 24h) |

### PTZ Control

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/ptz/move` | POST | Move camera (direction, speed) |
| `/ptz/preset/{id}` | POST | Go to preset position |
| `/ptz/track` | POST | Track person by name |
| `/ptz/stop` | POST | Stop tracking |

### Recording

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/recordings` | GET | List recordings |
| `/recordings/{id}` | GET | Download recording |
| `/snapshot/save` | POST | Save snapshot |

### Crew Manifest

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/crew` | GET | Currently visible people |
| `/crew/history` | GET | Entry/exit log |
| `/crew/{name}/last_seen` | GET | Last seen timestamp |

## MOTHER Integration

Example integration with MOTHER voice assistant:

```python
import httpx

# "Who's at the door?"
response = httpx.get("http://localhost:8200/faces")
faces = response.json()
# Returns: [{"name": "Oliver", "confidence": 0.95, "bbox": [...], "camera_id": "front_door"}]

# "Is anyone home?"
response = httpx.get("http://localhost:8200/crew")
crew = response.json()

# "When did Oliver leave?"
response = httpx.get("http://localhost:8200/crew/Oliver/last_seen")
last_seen = response.json()

# "Show me the front door"
# WebSocket connection to /stream/front_door

# "Track Oliver"
response = httpx.post("http://localhost:8200/ptz/track", json={
    "camera_id": "front_door",
    "target": "Oliver"
})
```

## WebSocket Events

Connect to `WS /events` to receive real-time updates:

```json
// Face detected
{
  "type": "faces_detected",
  "camera_id": "front_door",
  "timestamp": "2024-01-15T10:30:00",
  "data": {
    "faces": [{"name": "Oliver", "confidence": 0.95, "bbox": [100, 100, 200, 200], "known": true}]
  }
}

// Activity alert
{
  "type": "activity_alert",
  "camera_id": "front_door",
  "timestamp": "2024-01-15T10:30:00",
  "data": {
    "alert_type": "unknown_person",
    "description": "Unknown person detected",
    "severity": "high"
  }
}

// System status
{
  "type": "system_status",
  "camera_id": null,
  "timestamp": "2024-01-15T10:30:00",
  "data": {
    "online": true,
    "cameras": [...],
    "uptime_seconds": 3600
  }
}
```

## Face Enrollment

### Via API

```bash
curl -X POST "http://localhost:8200/faces/enroll" \
  -F "name=Oliver" \
  -F "image=@oliver.jpg"
```

### Via CLI

```bash
python -m src.face_enrollment enroll "Oliver" "path/to/oliver.jpg"
python -m src.face_enrollment list
python -m src.face_enrollment remove "Oliver"
```

## Project Structure

```
MOTHER VISION/
├── src/
│   ├── __init__.py
│   ├── api.py              # FastAPI server
│   ├── camera.py           # RTSP stream capture
│   ├── face_recognition.py # Face detection & matching
│   ├── face_enrollment.py  # Face enrollment
│   ├── motion_detection.py # Motion detection
│   ├── activity_detector.py# Suspicious activity detection
│   ├── ptz_control.py      # PTZ camera control
│   ├── tracker.py          # Person tracking
│   ├── recorder.py         # Video recording
│   └── events.py           # Event bus
├── web/                    # React frontend
│   ├── src/
│   │   ├── App.tsx
│   │   ├── api/client.ts   # API client
│   │   └── components/     # UI components
│   └── package.json
├── data/
│   ├── known_faces/        # Enrolled face images
│   ├── face_encodings.pkl  # Face embeddings
│   ├── recordings/         # Video clips
│   └── snapshots/          # Event screenshots
├── config.yaml
├── requirements.txt
├── main.py
└── README.md
```

## Hardware Requirements

### Minimum
- CPU: Intel i5 or equivalent
- RAM: 8GB
- Storage: 100GB+ for recordings

### Recommended (for GPU acceleration)
- GPU: NVIDIA GTX 1060 or better with CUDA
- CPU: Intel i7 or equivalent
- RAM: 16GB
- Storage: SSD with 500GB+

## Troubleshooting

### Camera not connecting
- Verify RTSP URL format: `rtsp://admin:PASSWORD@IP:554/h264Preview_01_main`
- Check camera is on same network
- Verify credentials

### Face recognition slow
- Use `model: "hog"` for CPU
- Use `model: "cnn"` with CUDA-enabled dlib for GPU
- Reduce frame processing scale

### High CPU usage
- Reduce number of cameras
- Increase frame skip in processing
- Lower motion detection sensitivity

## License

MIT License - See LICENSE file for details.

## Contributing

Contributions welcome! Please read CONTRIBUTING.md first.

---

**MOTHER VISION** - *I see everything.*

