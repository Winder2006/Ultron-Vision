# ULTRON VISION — Jetson MQTT vision service

Publishes vision events from the Jetson to Mother over MQTT. Camera frames
never leave the Jetson — all decode and inference is local; only JSON events
go over the wire.

```
Tapo C220/C225 ──RTSP/TCP──► nvv4l2decoder (NVDEC) ──► InsightFace (ArcFace)  ─┐
                                                   └─► YOLO (TensorRT)        ─┤
                                                                               ▼
                                                        presence trackers ──► MQTT
                                                                               ▼
                                            Mosquitto on the Jetson (0.0.0.0:1883)
                                                                               ▼
                                                             Mother (LAN subscriber)
```

## MQTT contract (topic prefix `mother/vision/`)

| Topic | Payload | Cadence |
|---|---|---|
| `face_detected` | `{"name": "Win", "confidence": 0.93, "ts": 1713000000}` | on arrival, then every ~7s while in frame (Mother stales at 120s) |
| `face_lost` | `{"name": "Win", "ts": 1713000030}` | once, when the face leaves the frame |
| `object_detected` | `{"label": "laptop", "confidence": 0.87, "ts": 1713000000}` | on arrival, then every ~60s while visible (Mother stales at 300s) |
| `room_occupancy` | `{"occupied": true, "person_count": 2, "ts": 1713000000}` | on change, **retained** — a freshly-connected Mother gets state immediately |
| `status` (extra) | `{"online": true}` | retained + Last Will, so Mother can tell "service dead" from "nothing happening" |

`ts` is epoch **seconds**. Unknown-but-present faces are sent with
`name: "unknown"` and confidence < 0.6.

**Confidence calibration** — Mother phrases identity by band
(`>0.85` name plainly / `0.6–0.85` "name (uncertain)" / `<0.6` "an
unidentified person"). ArcFace cosine similarity is mapped linearly onto
those bands via two anchors in `jetson/config.yaml`
(`sim_at_conf_060: 0.35`, `sim_at_conf_085: 0.55`). If Mother is too
eager/shy with names, tune the anchors — not Mother.

## Setup (on the Jetson)

### 1. Broker
```bash
sudo bash scripts/setup_mosquitto.sh
```
Installs Mosquitto listening on `0.0.0.0:1883`, anonymous allowed (home-LAN
start; the script comments show how to add auth later). Point Mother at
`mqtt://<jetson-ip>:1883`.

### 2. Camera (Tapo C220/C225)
In the Tapo app: **Camera Settings → Advanced Settings → Camera Account** —
create a local camera account (this is *not* your TP-Link cloud login). Then
in `jetson/config.yaml`:
```yaml
camera:
  rtsp_url: "rtsp://<camera-account-user>:<pass>@<cam-ip>:554/stream1"  # 2K main
  codec: "h264"   # set "h265" if you changed it in the app
```
Give the camera a DHCP reservation in your router so the IP doesn't move.

### 3. Python deps
Use the venv from `setup_orin.sh` (`--system-site-packages` so JetPack's
CUDA+GStreamer OpenCV is visible):
```bash
source venv/bin/activate
pip install -r jetson/requirements.txt
```

#### GPU wheels (Jetson-specific — PyPI's aarch64 builds won't use the GPU)
- **onnxruntime-gpu** (InsightFace on GPU): grab the wheel matching your
  JetPack from the [Jetson Zoo](https://elinux.org/Jetson_Zoo#ONNX_Runtime),
  e.g. `pip install onnxruntime_gpu-<ver>-cp3x-cp3x-linux_aarch64.whl`.
- **torch** (YOLO fallback + engine export): install NVIDIA's Jetson wheel per
  the [PyTorch for Jetson thread](https://forums.developer.nvidia.com/t/pytorch-for-jetson/72048).

Verify: `python -c "import onnxruntime; print(onnxruntime.get_available_providers())"`
should list `CUDAExecutionProvider`. The service also logs a warning at
startup if either engine ends up on CPU.

### 4. Models
```bash
mkdir -p models && cd models
# YOLO weights, then build the TensorRT engine ON the Jetson (not portable):
yolo export model=yolov8n.pt format=engine half=True
cd ..
```
InsightFace downloads its `buffalo_l` pack automatically on first run
(`~/.insightface/models/`).

### 5. Enroll faces
```bash
python -m jetson.enroll --name Win --image win1.jpg win2.jpg win3.jpg
# or straight from the camera (grabs 5 spaced samples):
python -m jetson.enroll --name Win --camera
python -m jetson.enroll --list
```
3–5 photos per person, varied angle/lighting. Embeddings are stored in
`data/faces/` — **gitignored and encrypted at rest** (Fernet; key sits next
to the store with 0600 perms — this is biometric data on real people, keep it
on the Jetson).

### 6. Run
```bash
python -m jetson.vision_service            # foreground
python -m jetson.vision_service --verbose  # log every publish
```
Watch the events from any LAN machine:
```bash
mosquitto_sub -h <jetson-ip> -t 'mother/vision/#' -v
```

### 7. Run as a service
```bash
sudo cp scripts/ultron-vision-mqtt.service /etc/systemd/system/
sudo sed -i "s/<user>/$USER/g" /etc/systemd/system/ultron-vision-mqtt.service
sudo systemctl daemon-reload
sudo systemctl enable --now ultron-vision-mqtt
journalctl -u ultron-vision-mqtt -f
```

## Troubleshooting
- **`gstreamer-nvdec` not the active backend** (startup warning): codec
  mismatch is the usual cause — Tapo `stream1` is H.264 unless you switched
  it; check `camera.codec`. Also confirm JetPack's OpenCV:
  `python -c "import cv2; print(cv2.getBuildInformation())" | grep GStreamer`.
- **RTSP auth fails**: you used your TP-Link cloud login — create the
  separate Camera Account in the app.
- **Everyone is "unknown"**: nothing enrolled (`--list`), or similarity
  anchors too strict — log with `--verbose` and lower `sim_at_conf_060`.
- **Occupancy flaps**: raise `occupancy.smoothing_seconds` or
  `objects.min_confidence`.
- **InsightFace/YOLO on CPU**: wrong wheels — see "GPU wheels" above.
