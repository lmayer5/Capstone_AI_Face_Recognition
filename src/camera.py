"""
Platform-aware camera abstraction.
Uses Picamera2 on Raspberry Pi, falls back to OpenCV VideoCapture on desktop.
Both classes expose a consistent read() / release() interface.
"""
import cv2
import sys
import os

# Add project root to path so we can import config
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import config


class DesktopCamera:
    """OpenCV VideoCapture wrapper for USB webcams (Windows/Mac/Linux desktop)."""

    def __init__(self, index=0, resolution=None):
        res = resolution or config.CAMERA_RESOLUTION
        self.cap = cv2.VideoCapture(index)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, res[0])
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, res[1])

        if not self.cap.isOpened():
            raise RuntimeError("Could not open desktop camera")
        print(f"[CAMERA] DesktopCamera opened (index={index}, resolution={res})")

    def read(self):
        """Returns (success: bool, frame: numpy array in BGR)."""
        return self.cap.read()

    def release(self):
        self.cap.release()


class PiCamera:
    """Picamera2 wrapper for the Raspberry Pi Camera Module."""

    def __init__(self, resolution=None):
        try:
            from picamera2 import Picamera2
        except ImportError:
            raise RuntimeError(
                "picamera2 is not installed. Install with: sudo apt install -y python3-picamera2"
            )

        res = resolution or config.CAMERA_RESOLUTION
        self.picam2 = Picamera2()

        # Configure for video/preview capture in BGR format (OpenCV compatible)
        cam_config = self.picam2.create_preview_configuration(
            main={"size": res, "format": "BGR888"}
        )
        self.picam2.configure(cam_config)
        self.picam2.start()
        print(f"[CAMERA] PiCamera opened (resolution={res})")

    def read(self):
        """Returns (success: bool, frame: numpy array in BGR) — matches OpenCV interface."""
        try:
            frame = self.picam2.capture_array()
            return True, frame
        except Exception as e:
            print(f"[CAMERA] Capture error: {e}")
            return False, None

    def release(self):
        self.picam2.stop()
        self.picam2.close()


def get_camera(resolution=None):
    """
    Factory function: returns PiCamera on Raspberry Pi, DesktopCamera otherwise.
    """
    if config.IS_PI:
        try:
            return PiCamera(resolution=resolution)
        except RuntimeError as e:
            print(f"[CAMERA] PiCamera failed ({e}), falling back to OpenCV...")
            return DesktopCamera(resolution=resolution)
    else:
        return DesktopCamera(resolution=resolution)
