#!/usr/bin/env bash
# ULTRON VISION — one-shot setup for NVIDIA Jetson Orin AGX
# Run from the repo root on the Orin:  bash setup_orin.sh
set -e

echo "============================================"
echo " ULTRON VISION — Orin AGX setup"
echo "============================================"

# --- sanity: are we on the Orin / in the repo? ---
if [ ! -f main.py ] || [ ! -f requirements-jetson.txt ]; then
  echo "ERROR: run this from the cloned repo root (where main.py lives)."
  exit 1
fi

# --- 0. confirm JetPack OpenCV has CUDA + GStreamer ---
echo
echo ">>> Checking system OpenCV for CUDA + GStreamer..."
python3 - <<'PY'
import cv2
info = cv2.getBuildInformation()
cuda = "NVIDIA CUDA:" in info and "YES" in info.split("NVIDIA CUDA:")[1][:20]
gst  = "GStreamer:" in info and "YES" in info.split("GStreamer:")[1][:20]
print(f"    OpenCV {cv2.__version__}  CUDA={'YES' if cuda else 'NO'}  GStreamer={'YES' if gst else 'NO'}")
if not (cuda and gst):
    print("    WARNING: system OpenCV is missing CUDA or GStreamer.")
    print("    Do NOT pip install opencv-python. Install 'nvidia-jetpack' instead.")
PY

# --- 1. venv with system site packages (so it sees JetPack OpenCV) ---
echo
echo ">>> Creating venv (--system-site-packages)..."
if [ ! -d venv ]; then
  python3 -m venv venv --system-site-packages
fi
# shellcheck disable=SC1091
source venv/bin/activate
pip install --upgrade pip

# --- 2. python deps (NO opencv/dlib here) ---
echo
echo ">>> Installing Python dependencies..."
pip install -r requirements-jetson.txt

# --- 3. dlib with CUDA (skip if already built with CUDA) ---
echo
echo ">>> Checking dlib CUDA support..."
DLIB_OK=$(python3 -c "import dlib; print(1 if getattr(dlib,'DLIB_USE_CUDA',False) and dlib.cuda.get_num_devices()>0 else 0)" 2>/dev/null || echo 0)
if [ "$DLIB_OK" = "1" ]; then
  echo "    dlib already built with CUDA — skipping build."
else
  echo "    Building dlib from source with CUDA (this takes 20-40 min)..."
  sudo apt-get update
  sudo apt-get install -y build-essential cmake libopenblas-dev liblapack-dev
  if [ ! -d /tmp/dlib_build ]; then
    git clone https://github.com/davisking/dlib.git /tmp/dlib_build
  fi
  ( cd /tmp/dlib_build && python setup.py install --set DLIB_USE_CUDA=1 --set USE_AVX_INSTRUCTIONS=1 )
  pip install face_recognition --no-deps
fi

# --- 4. verify ---
echo
echo ">>> Verifying CUDA dlib..."
python3 -c "import dlib; print('    dlib CUDA:', dlib.DLIB_USE_CUDA, '| devices:', dlib.cuda.get_num_devices())"

echo
echo "============================================"
echo " Setup complete. Next:"
echo "   1. Edit config.yaml — set model: \"cnn\" and add your RTSP cameras"
echo "   2. (optional) sudo nvpmodel -m 0 && sudo jetson_clocks"
echo "   3. source venv/bin/activate && python main.py"
echo "   4. Check GPU:  curl http://localhost:8200/status"
echo "============================================"
