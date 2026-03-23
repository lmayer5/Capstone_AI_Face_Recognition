"""
Centralized configuration for the Face Recognition Security System.
Auto-detects platform (Raspberry Pi vs Desktop) and sets defaults accordingly.
"""
import platform

# --- Platform Detection ---
_machine = platform.machine().lower()
IS_PI = _machine in ("aarch64", "armv7l", "armv8l")

# --- Camera Settings ---
# Lower resolution improves performance on Pi
CAMERA_RESOLUTION = (640, 480) if IS_PI else (1280, 720)

# --- Display ---
# Set to True to disable cv2.imshow() windows (for headless/SSH operation)
# Since user confirmed a monitor will be connected, default is False on all platforms
HEADLESS = False

# --- Camera & Power ---
CAMERA_IDLE_TIMEOUT = 30.0     # Turn off camera if no faces/motion/RFIDs seen

# --- Door Lock / Hardware ---
AUTO_LOCK_DELAY = 5.0          # Seconds before auto-locking after access granted
RECOGNITION_COOLDOWN = 2.0     # Seconds the recognition thread sleeps after a match

# GPIO Pin Assignments (BCM numbering)
GPIO_GREEN_LED = 17            # Green LED  — Access Granted / Door Unlocked
GPIO_YELLOW_LED = 27           # Yellow LED — Scanning / Processing
GPIO_RED_LED = 22              # Red LED    — Locked / Unknown Face

# Door Strike & Sensor
GPIO_RELAY = 23                # Relay module controlling the electric/magnetic strike
GPIO_REED_SWITCH = 24          # Magnetic Reed Switch for door open/close detection
GPIO_PIR = 25                  # PIR motion detector

# --- Face Detection ---
# MediaPipe model_selection: 0 = short-range (within 2m, faster), 1 = full-range (within 5m)
DETECTION_MODEL_SELECTION = 0 if IS_PI else 1
DETECTION_MIN_CONFIDENCE = 0.5

# --- Face Recognition ---
RECOGNITION_MODEL = "Facenet512"
RECOGNITION_THRESHOLD = 0.4    # Cosine distance threshold
DB_PATH = "db/authorized_users"
