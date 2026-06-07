"""
Laptop webcam -> MJPEG HTTP stream, so a remote machine (the Orin) can pull it
in like an IP camera.

Run on the LAPTOP (with the project venv that has OpenCV):
    venv\\Scripts\\python.exe webcam_stream.py

Then point the Orin's config.yaml camera at:
    http://192.168.1.20:8554/video
"""
import cv2
import sys
import time
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8554
DEVICE = 0          # change to 1 if you have multiple webcams
JPEG_QUALITY = 80
FPS_CAP = 20

# Open the webcam (CAP_DSHOW is the reliable backend on Windows)
cap = cv2.VideoCapture(DEVICE, cv2.CAP_DSHOW)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
if not cap.isOpened():
    print(f"ERROR: could not open webcam device {DEVICE}.")
    print("Close any app using the camera (Zoom/Teams/browser) and retry.")
    sys.exit(1)

_lock = threading.Lock()
_latest = {"jpg": None}


def _grabber():
    """Single capture thread -> shared latest-JPEG buffer (thread-safe)."""
    while True:
        ok, frame = cap.read()
        if not ok:
            time.sleep(0.05)
            continue
        ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        if ok:
            with _lock:
                _latest["jpg"] = jpg.tobytes()


threading.Thread(target=_grabber, daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/video":
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()
        try:
            while True:
                with _lock:
                    data = _latest["jpg"]
                if data is None:
                    time.sleep(0.05)
                    continue
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n")
                self.wfile.write(f"Content-Length: {len(data)}\r\n\r\n".encode())
                self.wfile.write(data)
                self.wfile.write(b"\r\n")
                time.sleep(1.0 / FPS_CAP)
        except (BrokenPipeError, ConnectionResetError):
            pass  # client (the Orin) disconnected — normal

    def log_message(self, *args):
        pass  # silence per-request logging


if __name__ == "__main__":
    print(f"Webcam streaming on  http://192.168.1.20:{PORT}/video")
    print("Leave this window open. Press Ctrl+C to stop.")
    print("If Windows asks about firewall access, click 'Allow'.")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
