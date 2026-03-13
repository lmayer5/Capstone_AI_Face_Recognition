# AI Face Recognition Security System

A real-time facial recognition door lock system using MediaPipe for detection and DeepFace (FaceNet512) for recognition. Runs on both **Windows (desktop)** and **Raspberry Pi 4B**.

## Quick Start (Desktop / Windows)

1. Install dependencies: `pip install -r requirements.txt`
2. Enroll a user: `python enroll.py`
3. Run the system: `python main.py`
4. Press `q` to quit.

## Raspberry Pi 4B Deployment

### Hardware Required

- Raspberry Pi 4B (4 GB RAM recommended)
- Raspberry Pi Camera Module (V2 or V3)
- Breadboard with 3 LEDs + resistors (220Ω):
  - **Green LED** → GPIO 17 (BCM) — Access Granted / Unlocked
  - **Yellow LED** → GPIO 27 (BCM) — Scanning / Processing
  - **Red LED** → GPIO 22 (BCM) — Locked / Unknown Face
- Monitor connected via HDMI (for live camera feed and status)
- Heatsink + fan recommended (ML inference generates heat)

### Wiring Diagram

```
GPIO 17 ──[220Ω]──▶ Green LED  ──▶ GND
GPIO 27 ──[220Ω]──▶ Yellow LED ──▶ GND
GPIO 22 ──[220Ω]──▶ Red LED    ──▶ GND
```

### OS Setup

1. Flash **Raspberry Pi OS 64-bit** (Bullseye or later) using Raspberry Pi Imager
2. Enable the camera: `sudo raspi-config` → Interface Options → Camera → Enable
3. Update the system:
   ```bash
   sudo apt update && sudo apt upgrade -y
   ```
4. Install picamera2 (may already be pre-installed):
   ```bash
   sudo apt install -y python3-picamera2
   ```

### Installation

```bash
# Create a virtual environment (use --system-site-packages for picamera2 access)
python3 -m venv --system-site-packages venv
source venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt
```

### Running

```bash
# Enroll users
python enroll.py

# Run the security system
python main.py
```

### LED Status Indicators

| LED      | State        | Meaning                        |
|----------|-------------|--------------------------------|
| 🔴 Red    | Solid ON    | System locked / No match       |
| 🟡 Yellow | Solid ON    | Scanning a face                |
| 🟢 Green  | Solid ON    | Access granted (auto-locks after 5s) |

### Performance Expectations

- **Face detection**: ~10–15 FPS (MediaPipe, short-range mode)
- **Face recognition**: ~1–2 FPS (FaceNet512 via DeepFace)
- The threaded architecture keeps the camera feed smooth while recognition runs in the background.

## Configuration

Edit `config.py` to customize:

| Setting                    | Default (Pi)  | Default (Desktop) | Description                 |
|----------------------------|--------------|--------------------|------------------------------|
| `CAMERA_RESOLUTION`        | 640×480      | 1280×720           | Camera capture resolution    |
| `HEADLESS`                 | False        | False              | Disable GUI windows          |
| `AUTO_LOCK_DELAY`          | 5.0s         | 5.0s               | Seconds before auto-lock     |
| `GPIO_GREEN_LED`           | 17           | —                  | Green LED pin (BCM)          |
| `GPIO_YELLOW_LED`          | 27           | —                  | Yellow LED pin (BCM)         |
| `GPIO_RED_LED`             | 22           | —                  | Red LED pin (BCM)            |
| `DETECTION_MODEL_SELECTION`| 0 (fast)     | 1 (full-range)     | MediaPipe model selection    |

## Project Structure

```
├── main.py              # Main security loop
├── enroll.py            # User enrollment script
├── config.py            # Centralized configuration
├── requirements.txt     # Python dependencies
├── db/                  # Auto-created at runtime
│   ├── authorized_users/  # Stored face embeddings (.pkl)
│   └── events.db          # Access log (SQLite)
└── src/
    ├── camera.py        # Platform-aware camera (Picamera2 / OpenCV)
    ├── detector.py      # MediaPipe face detection
    ├── recognizer.py    # DeepFace FaceNet512 recognition
    ├── hardware.py      # GPIO LED control + mock mode
    ├── database.py      # SQLite event logging
    └── async_utils.py   # Threaded recognition pipeline
```
