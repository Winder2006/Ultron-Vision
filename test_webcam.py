"""
Quick webcam test script - Verify your webcam works before running the full system
"""

import cv2
import sys

def test_webcam(index=0):
    print(f"Testing webcam at index {index}...")
    print("Press 'q' to quit, 's' to save a snapshot")
    print("-" * 40)
    
    # Try DirectShow on Windows
    cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
    
    if not cap.isOpened():
        print(f"[ERROR] Could not open webcam {index}")
        print("\nTry these fixes:")
        print("  1. Make sure no other app is using the camera")
        print("  2. Try a different index: python test_webcam.py 1")
        print("  3. Check Windows camera permissions")
        return False
    
    # Set resolution
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    
    # Get actual resolution
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    
    print(f"[OK] Webcam opened successfully!")
    print(f"     Resolution: {width}x{height}")
    print(f"     FPS: {fps}")
    print()
    
    frame_count = 0
    
    while True:
        ret, frame = cap.read()
        
        if not ret:
            print("[ERROR] Failed to read frame")
            break
        
        frame_count += 1
        
        # Add text overlay
        cv2.putText(
            frame, 
            f"MOTHER VISION - Webcam Test (Frame {frame_count})",
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 127),
            2
        )
        cv2.putText(
            frame,
            "Press 'q' to quit, 's' to save snapshot",
            (10, height - 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (200, 200, 200),
            1
        )
        
        # Show frame
        cv2.imshow("MOTHER VISION - Webcam Test", frame)
        
        key = cv2.waitKey(1) & 0xFF
        
        if key == ord('q'):
            break
        elif key == ord('s'):
            filename = f"test_snapshot_{frame_count}.jpg"
            cv2.imwrite(filename, frame)
            print(f"[SAVED] {filename}")
    
    cap.release()
    cv2.destroyAllWindows()
    
    print(f"\nTest complete! Captured {frame_count} frames.")
    return True


def list_cameras():
    """List available camera indices"""
    print("Scanning for available cameras...")
    available = []
    
    for i in range(5):
        cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
        if cap.isOpened():
            ret, _ = cap.read()
            if ret:
                available.append(i)
                print(f"  [FOUND] Camera at index {i}")
            cap.release()
    
    if not available:
        print("  [NONE] No cameras found")
    
    return available


if __name__ == "__main__":
    print("=" * 40)
    print("MOTHER VISION - Webcam Test")
    print("=" * 40)
    print()
    
    # List available cameras
    cameras = list_cameras()
    print()
    
    # Get camera index from args or use default
    index = 0
    if len(sys.argv) > 1:
        try:
            index = int(sys.argv[1])
        except ValueError:
            print(f"Invalid index: {sys.argv[1]}")
            sys.exit(1)
    
    # Run test
    if cameras:
        test_webcam(index)
    else:
        print("No cameras available to test.")
        sys.exit(1)

