"""
Platform-aware camera abstraction.
Uses Picamera2 on Raspberry Pi, falls back to OpenCV VideoCapture on desktop.
Both classes expose a consistent read() / release() interface.
"""
#import cv2
#mport sys
#import os

# Add project root to path so we can import config
#sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
#import config
#import sys
# This forces Python to look in House A (the system) for the camera drivers
#sys.path.insert(1, '/usr/lib/python3/dist-packages')


# class DesktopCamera:
#     """OpenCV VideoCapture wrapper for USB webcams (Windows/Mac/Linux desktop)."""

#     def __init__(self, index=0, resolution=None):
#         res = resolution or config.CAMERA_RESOLUTION
#         self.cap = cv2.VideoCapture(index)
#         self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, res[0])
#         self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, res[1])

#         if not self.cap.isOpened():
#             raise RuntimeError("Could not open desktop camera")
#         print(f"[CAMERA] DesktopCamera opened (index={index}, resolution={res})")

#     def read(self):
#         """Returns (success: bool, frame: numpy array in BGR)."""
#         return self.cap.read()

#     def release(self):
#         self.cap.release()

# Instead of cv2, use the official Pi camera

import subprocess
import numpy as np
import cv2
import atexit
class DesktopCamera:
    def __init__(self):
        self.width = 640
        self.height = 480
        # The camera outputs YUV420 format, which uses 1.5 bytes per pixel
        self.frame_bytes = int(self.width * self.height * 1.5)
        
        # This asks the Operating System to run the camera, completely ignoring Python versions
        self.cmd = [
            "rpicam-vid",
            "-t", "0",           # Run forever
            "--width", str(self.width),
            "--height", str(self.height),
            "--framerate", "15", # 15 FPS gives the Pi 4 time to run AI calculations
            "--codec", "yuv420", # Raw, uncompressed video data
            "-o", "-"            # Output directly to Python (stdout)
        ]
        
        # Start the camera quietly in the background
        self.process = subprocess.Popen(self.cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        # <-- 2. Register the emergency stop button
        atexit.register(self.release)



    def read(self):
        # Read exactly one frame of video
        raw_data = self.process.stdout.read(self.frame_bytes)
        
        if len(raw_data) != self.frame_bytes:
            return False, None
            
        # Convert the raw numbers into a colorful picture for OpenCV
        yuv_image = np.frombuffer(raw_data, dtype=np.uint8).reshape((int(self.height * 1.5), self.width))
        bgr_image = cv2.cvtColor(yuv_image, cv2.COLOR_YUV2BGR_I420)
        
        return True, bgr_image

    def release(self):
# <-- 3. Make sure the release function actually kills the process cleanly
        if hasattr(self, 'process') and self.process.poll() is None:
            self.process.kill()
            self.process.wait() # Wait for the camera to actually power down

# Make sure this matches how enroll.py calls your camera
def get_camera():
    return DesktopCamera()

        

# class PiCamera:
#     """Picamera2 wrapper for the Raspberry Pi Camera Module."""

#     def __init__(self, resolution=None):
#         try:
#             from picamera2 import Picamera2
#         except ImportError:
#             raise RuntimeError(
#                 "picamera2 is not installed. Install with: sudo apt install -y python3-picamera2"
#             )

#         res = resolution or config.CAMERA_RESOLUTION
#         self.picam2 = Picamera2()

#         # Configure for video/preview capture in BGR format (OpenCV compatible)
#         cam_config = self.picam2.create_preview_configuration(
#             main={"size": res, "format": "BGR888"}
#         )
#         self.picam2.configure(cam_config)
#         self.picam2.start()
#         print(f"[CAMERA] PiCamera opened (resolution={res})")

#     def read(self):
#         """Returns (success: bool, frame: numpy array in BGR) — matches OpenCV interface."""
#         try:
#             frame = self.picam2.capture_array()
#             return True, frame
#         except Exception as e:
#             print(f"[CAMERA] Capture error: {e}")
#             return False, None

#     def release(self):
#         self.picam2.stop()
#         self.picam2.close()


# def get_camera(resolution=None):
#     """
#     Factory function: returns PiCamera on Raspberry Pi, DesktopCamera otherwise.
#     """
#     if config.IS_PI:
#         try:
#             return PiCamera(resolution=resolution)
#         except RuntimeError as e:
#             print(f"[CAMERA] PiCamera failed ({e}), falling back to OpenCV...")
#             return DesktopCamera(resolution=resolution)
#     else:
#         return DesktopCamera(resolution=resolution)
