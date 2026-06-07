# ULTRON VISION — NVIDIA Jetson Orin AGX Deployment

Step-by-step for SSHing in, cloning, and running multi-camera facial
recognition on GPU.

## 0. Prerequisites on the Orin
- JetPack 5.x or 6.x flashed (includes CUDA, cuDNN, and a CUDA+GStreamer
  build of OpenCV).
- Confirm OpenCV sees CUDA + GStreamer:
  ```bash
  python3 -c "import cv2; print(cv2.__version__); print(cv2.getBuildInformation())" | grep -iE "CUDA|GStreamer"
  ```
  You want `NVIDIA CUDA: YES` and `GStreamer: YES`. If OpenCV is missing,
  install `nvidia-jetpack` — do NOT `pip install opencv-python`.

## 1. SSH in and clone
```bash
ssh <user>@<orin-ip>
git clone <your-repo-url> ultron-vision
cd ultron-vision
```

## 2. Python environment (use system OpenCV)
Create the venv with `--system-site-packages` so it can SEE the JetPack
OpenCV instead of pulling a CPU-only wheel:
```bash
python3 -m venv venv --system-site-packages
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements-jetson.txt
```

## 3. Build dlib with CUDA (GPU face recognition)
The pip dlib wheel is CPU-only. For `model: "cnn"` you must compile:
```bash
sudo apt-get update
sudo apt-get install -y build-essential cmake libopenblas-dev liblapack-dev

git clone https://github.com/davisking/dlib.git
cd dlib
python setup.py install --set DLIB_USE_CUDA=1 --set USE_AVX_INSTRUCTIONS=1
cd ..

# Then the Python wrapper (it will use the CUDA dlib you just built):
pip install face_recognition --no-deps
```
Verify CUDA dlib:
```bash
python3 -c "import dlib; print('CUDA:', dlib.DLIB_USE_CUDA, 'devices:', dlib.cuda.get_num_devices())"
```
Expect `CUDA: True devices: 1`.

## 4. Configure cameras (config.yaml)
- Set `face_recognition.model: "cnn"` to use the GPU.
- Add your RTSP cameras (multi-cam examples are commented in config.yaml):
  ```yaml
  cameras:
    - id: "cam1"
      name: "Entrance"
      rtsp_url: "rtsp://admin:PASSWORD@192.168.1.101:554/h264Preview_01_main"
      ptz_enabled: false
      api_url: null
  ```
- Point recordings at fast storage (NVMe, not eMMC):
  ```yaml
  recording:
    path: "/mnt/nvme/recordings"
  ```
- RTSP now uses TCP transport with an 8s connect/read timeout automatically
  (set in src/camera.py). For UDP override:
  `export OPENCV_FFMPEG_CAPTURE_OPTIONS="rtsp_transport;udp"`.

## 5. Max performance mode (optional but recommended)
```bash
sudo nvpmodel -m 0      # MAXN — all cores/clocks
sudo jetson_clocks      # lock clocks to max
```

## 6. Run
```bash
source venv/bin/activate
python main.py
```
API + dashboard backend on `http://<orin-ip>:8200`. Confirm GPU is live:
```bash
curl http://localhost:8200/status | python3 -m json.tool
# "gpu": {"available": true, "devices": 1, "backend": "dlib-cuda"}
```

## 7. Frontend (run on your laptop, point it at the Orin)
```bash
cd web
echo "VITE_API_BASE_URL=http://<orin-ip>:8200" > .env.local
npm install
npm run dev
```
The client reads `VITE_API_BASE_URL`; without it, it falls back to localhost.

## 8. Run as a service (survives reboot / disconnect)
Create `/etc/systemd/system/ultron-vision.service`:
```ini
[Unit]
Description=ULTRON VISION
After=network-online.target

[Service]
User=<user>
WorkingDirectory=/home/<user>/ultron-vision
ExecStart=/home/<user>/ultron-vision/venv/bin/python main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ultron-vision
journalctl -u ultron-vision -f   # live logs
```

## Troubleshooting
- **RTSP opens then drops** → already on TCP; check the URL path
  (`h264Preview_01_main` vs `_sub`) and credentials.
- **Face recog slow / 100% CPU** → dlib was NOT built with CUDA (step 3).
  Re-check `dlib.DLIB_USE_CUDA`.
- **`cv2` import pulls CPU build** → you pip-installed opencv-python into the
  venv. `pip uninstall opencv-python opencv-python-headless` and recreate the
  venv with `--system-site-packages`.
- **Thermals/throttling** → keep `jetson_clocks` on a good heatsink/fan; lower
  `recording.fps` and raise the face-recognition frame stride in
  `src/api.py` (`frame.frame_id % 5`) if needed.
