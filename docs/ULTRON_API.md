# ULTRON VISION — Integration API

Contract for external clients (Ultron/Mother) connecting to the vision system
on the Jetson Orin AGX. Everything below is LAN-only and unauthenticated —
do not expose these ports to the internet without adding auth (Tailscale or a
reverse proxy).

| Service            | Address                            | What it's for                    |
|--------------------|------------------------------------|----------------------------------|
| REST + WebSocket   | `http://192.168.1.202:8200`        | queries, events, snapshots       |
| go2rtc WebRTC      | `ws://192.168.1.202:1984/api/ws`   | real-time video                  |
| MQTT broker        | `192.168.1.202:1883`               | push events for Mother           |
| Interactive docs   | `http://192.168.1.202:8200/docs`   | live Swagger UI of every route   |

The camera id is `main_cam`. All bounding boxes are `[x, y, width, height]`
in full camera resolution (2560×1440).

---

## 1. REST — ask questions on demand

### Who is visible right now

```
GET /faces
→ [{"name": "Win", "confidence": 0.99, "bbox": [990, 641, 372, 502],
    "known": true, "camera_id": "main_cam"}]
```

`GET /faces/unknown` returns only `known: false` entries.

```
GET /crew
→ [{"name": "Win", "known": true, "cameras": ["main_cam"], "confidence": 0.99}]
```

### Presence history

```
GET /crew/{name}/last_seen
→ {"name": "Win", "camera_id": "main_cam",
   "last_seen": "2026-07-24T14:59:12.000000", "currently_visible": true}
   (404 if the person has never been seen)

GET /crew/history?hours=24     — entry/exit log
GET /activity/alerts?hours=24  — alerts (loitering, unknown_person,
                                 quiet_hours_motion, person_count_change)
GET /motion                    — current motion state per camera
```

### Seeing the room (for visual questions)

```
GET /snapshot              → image/jpeg, current full-res frame
GET /snapshot/{camera_id}  → same, explicit camera
```

For "what do you see / what is Win wearing" questions, fetch `/snapshot` and
pass the JPEG to a vision LLM together with `/faces` (so the answer can use
real identities). Example tool for Ultron's side:

```python
import base64, requests

VISION = "http://192.168.1.202:8200"

def look_through_camera(question: str) -> str:
    jpg = requests.get(f"{VISION}/snapshot", timeout=15).content
    faces = requests.get(f"{VISION}/faces", timeout=10).json()
    known = ", ".join(f"{f['name']} ({f['confidence']:.0%})" for f in faces) or "nobody recognized"
    import anthropic
    msg = anthropic.Anthropic().messages.create(
        model="claude-sonnet-5",
        max_tokens=500,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": base64.b64encode(jpg).decode()}},
            {"type": "text", "text":
                f"Camera feed. Face recognition says: {known}. {question}"},
        ]}],
    )
    return msg.content[0].text
```

Note: `/snapshot` can take a few seconds while the recorder is writing event
clips — use a generous timeout (15 s+).

### System health

```
GET /health → {"status": "healthy", "timestamp": "..."}
GET /status → {"online": true,
               "cameras": [{"camera_id": "main_cam", "online": true,
                            "fps": 14.0, "resolution": [2560, 1440],
                            "error": null}], ...}
```

### Management (occasionally useful)

```
POST   /faces/enroll           multipart form: name=<str>, image=<jpeg file>
GET    /faces/enrolled         enrolled people + sample counts
DELETE /faces/{name}           forget a person
GET    /recordings             list event recordings
GET    /recordings/{id}        download mp4
POST   /ptz/move|track|stop    camera pan/tilt (if enabled)
```

---

## 2. WebSocket `/events` — real-time push

Connect to `ws://192.168.1.202:8200/events`. Every message is JSON:

```json
{"type": "faces_detected",
 "camera_id": "main_cam",
 "timestamp": "2026-07-24T14:59:12.345678",
 "data": {"faces": [{"name": "Win", "confidence": 0.99,
                     "bbox": [990, 641, 372, 502], "known": true}],
          "frame_id": 12345}}
```

`type` is one of: `faces_detected` (≈10/s while someone is visible; empty
`faces` array means the room cleared — do not ignore it), `motion_detected`,
`activity_alert` (`data` has `alert_type`, `description`, `severity`,
`faces`), `tracking_status`, `camera_status`, `recording_event`,
`system_status`, plus `{"type": "ping"}` keepalives every second when idle
(ignore them). Reconnect with backoff on close — the backend restarts
whenever it is redeployed.

---

## 3. MQTT — the Mother contract (fire-and-forget push)

Broker on the Jetson, port 1883. Topic prefix `mother/vision/`, JSON
payloads, `ts` is epoch seconds. Events only — never frames.

```
face_detected   {"name": "Win", "confidence": 0.99, "ts": 1784100000}
face_lost       {"name": "Win", "ts": 1784100060}
object_detected {"label": "person", "confidence": 0.9, "ts": 1784100000}
room_occupancy  {"occupied": true, "person_count": 1, "ts": 1784100000}   [retained]
mother/vision/status {"online": true|false}                               [retained, Last Will]
```

Confidence bands (how Mother should phrase identity): > 0.85 state the name
plainly; 0.60–0.85 "name (uncertain)"; < 0.60 arrives as name `"unknown"`.
`room_occupancy` and `status` are retained, so a subscriber learns current
state immediately on connect.

---

## 4. Live video in a frontend

Use go2rtc's WebRTC client (vendored in this repo at
`web/src/vendor/video-rtc.js` — copy it into Ultron's frontend):

```js
import { VideoRTC } from './video-rtc.js';
customElements.define('video-stream', VideoRTC);

const el = document.createElement('video-stream');
el.mode = 'webrtc';
el.src = 'ws://192.168.1.202:1984/api/ws?src=main_cam';
container.appendChild(el);
```

Sub-second latency, H264 passthrough (no re-encode). The JPEG fallback is
`ws://192.168.1.202:8200/stream/main_cam` (~14 fps, higher latency): binary
frames are JPEGs, text frames are JSON metadata.
