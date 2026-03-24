from __future__ import annotations

import json
import os
import pickle
import sys
import time
from typing import Optional, Tuple

import requests

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "pi_project", "Capstone_AI_Face_Recognition-main")
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.camera import get_camera
from src.detector import FaceDetector
from src.recognizer import FaceIdentifier
import config

BACKEND_BASE = os.getenv("BACKEND_BASE", "http://10.0.0.11:8080")
DEVICE_TOKEN = os.getenv("DEVICE_TOKEN", "")
DEVICE_NAME = os.getenv("PI_DEVICE_NAME", "raspberry-pi-1")

POLL_INTERVAL_SECONDS = float(os.getenv("ENROLLMENT_POLL_INTERVAL", "2.0"))
MAX_CAPTURE_SECONDS = float(os.getenv("ENROLLMENT_CAPTURE_TIMEOUT", "20.0"))
REQUIRED_STABLE_FRAMES = int(os.getenv("ENROLLMENT_STABLE_FRAMES", "8"))
RFID_TIMEOUT_SECONDS = float(os.getenv("RFID_CAPTURE_TIMEOUT", "15.0"))

ACCESS_FACE_WINDOW_SECONDS = float(os.getenv("ACCESS_FACE_WINDOW_SECONDS", "8.0"))
ACCESS_LOOP_SLEEP_SECONDS = float(os.getenv("ACCESS_LOOP_SLEEP_SECONDS", "0.1"))
FACE_RETRY_SECONDS = float(os.getenv("FACE_RETRY_SECONDS", "0.05"))
DOOR_UNLOCK_SECONDS = float(os.getenv("DOOR_UNLOCK_SECONDS", str(getattr(config, "AUTO_LOCK_DELAY", 5.0))))
DOOR_OPEN_TIMEOUT_SECONDS = float(os.getenv("DOOR_OPEN_TIMEOUT_SECONDS", "10.0"))
DOOR_CLOSE_TIMEOUT_SECONDS = float(os.getenv("DOOR_CLOSE_TIMEOUT_SECONDS", "30.0"))
POST_ACCESS_COOLDOWN_SECONDS = float(os.getenv("POST_ACCESS_COOLDOWN_SECONDS", "2.0"))

FACE_CROP_PADDING = int(os.getenv("FACE_CROP_PADDING", "20"))

# GPIO pins from config.py
GPIO_GREEN_LED = getattr(config, "GPIO_GREEN_LED", 17)
GPIO_YELLOW_LED = getattr(config, "GPIO_YELLOW_LED", 27)
GPIO_RED_LED = getattr(config, "GPIO_RED_LED", 22)
GPIO_RELAY = getattr(config, "GPIO_RELAY", 23)
GPIO_REED_SWITCH = getattr(config, "GPIO_REED_SWITCH", 24)
GPIO_PIR = getattr(config, "GPIO_PIR", 25)


class PiAgent:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.detector = FaceDetector()
        self.recognizer = FaceIdentifier()
        self.camera = get_camera()
        self.headers = {"x-device-token": DEVICE_TOKEN} if DEVICE_TOKEN else {}

        self.rfid_reader = self._init_rfid_reader()
        self.GPIO = self._init_gpio()

        self.last_access_attempt_at = 0.0
        self.last_motion_at = 0.0
        self.last_face_name: Optional[str] = None

    # ----------------------------
    # Hardware init
    # ----------------------------
    def _init_gpio(self):
        try:
            import RPi.GPIO as GPIO  # type: ignore

            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)

            GPIO.setup(GPIO_GREEN_LED, GPIO.OUT)
            GPIO.setup(GPIO_YELLOW_LED, GPIO.OUT)
            GPIO.setup(GPIO_RED_LED, GPIO.OUT)
            GPIO.setup(GPIO_RELAY, GPIO.OUT)

            # Pull-ups are usually appropriate for reed/PIR inputs if wiring supports it.
            # Adjust if your specific hardware requires different behavior.
            GPIO.setup(GPIO_REED_SWITCH, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.setup(GPIO_PIR, GPIO.IN)

            # Default states
            GPIO.output(GPIO_GREEN_LED, GPIO.LOW)
            GPIO.output(GPIO_YELLOW_LED, GPIO.LOW)
            GPIO.output(GPIO_RED_LED, GPIO.HIGH)   # locked / idle
            GPIO.output(GPIO_RELAY, GPIO.LOW)      # locked

            print("[PI] GPIO initialized.")
            return GPIO
        except Exception as exc:
            print(f"[PI] GPIO unavailable, running without hardware GPIO control: {exc}")
            return None

    def _init_rfid_reader(self):
        try:
            from mfrc522 import SimpleMFRC522  # type: ignore
            print("[PI] RFID reader initialized (SimpleMFRC522).")
            return SimpleMFRC522()
        except Exception as exc:
            print(f"[PI] SimpleMFRC522 unavailable: {exc}")

        try:
            from src.rfid_reader import RFIDReader  # type: ignore
            print("[PI] RFID reader initialized (project RFIDReader).")
            return RFIDReader()
        except Exception as exc:
            print(f"[PI] Project RFID reader unavailable: {exc}")
            print("[PI] Set MOCK_RFID_UID to simulate card taps during testing.")
            return None

    # ----------------------------
    # GPIO helpers
    # ----------------------------
    def _led_idle_locked(self) -> None:
        if not self.GPIO:
            return
        self.GPIO.output(GPIO_GREEN_LED, self.GPIO.LOW)
        self.GPIO.output(GPIO_YELLOW_LED, self.GPIO.LOW)
        self.GPIO.output(GPIO_RED_LED, self.GPIO.HIGH)

    def _led_scanning(self) -> None:
        if not self.GPIO:
            return
        self.GPIO.output(GPIO_GREEN_LED, self.GPIO.LOW)
        self.GPIO.output(GPIO_YELLOW_LED, self.GPIO.HIGH)
        self.GPIO.output(GPIO_RED_LED, self.GPIO.LOW)

    def _led_access_granted(self) -> None:
        if not self.GPIO:
            return
        self.GPIO.output(GPIO_GREEN_LED, self.GPIO.HIGH)
        self.GPIO.output(GPIO_YELLOW_LED, self.GPIO.LOW)
        self.GPIO.output(GPIO_RED_LED, self.GPIO.LOW)

    def _led_access_denied(self) -> None:
        if not self.GPIO:
            return
        self.GPIO.output(GPIO_GREEN_LED, self.GPIO.LOW)
        self.GPIO.output(GPIO_YELLOW_LED, self.GPIO.LOW)
        self.GPIO.output(GPIO_RED_LED, self.GPIO.HIGH)

    def _unlock_door(self) -> None:
        if not self.GPIO:
            print("[PI] Simulated unlock (GPIO unavailable).")
            return
        self.GPIO.output(GPIO_RELAY, self.GPIO.HIGH)

    def _lock_door(self) -> None:
        if not self.GPIO:
            print("[PI] Simulated lock (GPIO unavailable).")
            return
        self.GPIO.output(GPIO_RELAY, self.GPIO.LOW)

    def _motion_detected(self) -> bool:
        mock = os.getenv("MOCK_MOTION", "").strip().lower()
        if mock in {"1", "true", "yes"}:
            return True

        if not self.GPIO:
            return False

        try:
            return bool(self.GPIO.input(GPIO_PIR))
        except Exception:
            return False

    def _door_is_open(self) -> bool:
        """
        Assumes reed switch input is LOW when door is closed and HIGH when open.
        Flip the logic here if your wiring is the reverse.
        """
        mock = os.getenv("MOCK_DOOR_OPEN", "").strip().lower()
        if mock in {"1", "true", "yes"}:
            return True

        if not self.GPIO:
            return False

        try:
            raw = self.GPIO.input(GPIO_REED_SWITCH)
            return bool(raw)
        except Exception:
            return False
    def _read_frame(self) -> Tuple[bool, Optional[object]]:
        """
        Handles both camera APIs:
        - returns (ok, frame) directly
        - or returns just frame
        """
        try:
            result = self.camera.read()
        except Exception as exc:
            print(f"[PI] Camera read failed: {exc}")
            return False, None

        if isinstance(result, tuple) and len(result) == 2:
            ok, frame = result
            return bool(ok), frame

        if result is None:
            return False, None

        return True, result

    def _crop_face(self, frame, face_box):
        x, y, w, h = face_box

        x1 = max(0, x - FACE_CROP_PADDING)
        y1 = max(0, y - FACE_CROP_PADDING)
        x2 = min(frame.shape[1], x + w + FACE_CROP_PADDING)
        y2 = min(frame.shape[0], y + h + FACE_CROP_PADDING)

        crop = frame[y1:y2, x1:x2]
        if crop is None or crop.size == 0:
            return None
        return crop

    def _capture_embedding(self):
        print("[PI] Capturing face embedding...")
        start = time.time()
        stable = 0
        embedding = None

        while time.time() - start < MAX_CAPTURE_SECONDS:
            ok, frame = self._read_frame()
            if not ok or frame is None:
                time.sleep(FACE_RETRY_SECONDS)
                continue

            faces = self.detector.detect(frame)
            if len(faces) != 1:
                stable = 0
                time.sleep(FACE_RETRY_SECONDS)
                continue

            face_crop = self._crop_face(frame, faces[0])
            if face_crop is None:
                stable = 0
                time.sleep(FACE_RETRY_SECONDS)
                continue

            emb = self.recognizer.get_embedding(face_crop)
            if emb is None:
                stable = 0
                time.sleep(FACE_RETRY_SECONDS)
                continue

            embedding = emb
            stable += 1

            if stable >= REQUIRED_STABLE_FRAMES:
                print("[PI] Stable face capture complete.")
                return embedding

            time.sleep(FACE_RETRY_SECONDS)

        raise RuntimeError("Timed out waiting for a stable single-face capture")

    def _recognize_face_for_access(self, timeout_seconds: float = ACCESS_FACE_WINDOW_SECONDS) -> Optional[str]:
        """
        Returns recognized face_name or None.
        Keeps backend contract unchanged by returning a string name only.
        """
        start = time.time()
        best_name = None
        best_distance = float("inf")

        while time.time() - start < timeout_seconds:
            ok, frame = self._read_frame()
            if not ok or frame is None:
                time.sleep(FACE_RETRY_SECONDS)
                continue

            faces = self.detector.detect(frame)
            if len(faces) != 1:
                time.sleep(FACE_RETRY_SECONDS)
                continue

            face_crop = self._crop_face(frame, faces[0])
            if face_crop is None:
                time.sleep(FACE_RETRY_SECONDS)
                continue

            name, distance = self.recognizer.verify(face_crop)

            if name not in {"Unknown", "Error"}:
                if distance < best_distance:
                    best_distance = distance
                    best_name = name

                # one clean recognition is enough here
                print(f"[PI] Recognized {best_name} (distance={best_distance:.4f})")
                return best_name

            time.sleep(FACE_RETRY_SECONDS)

        return best_name
    def _save_embedding(self, face_name: str, embedding) -> str:
        os.makedirs(config.DB_PATH, exist_ok=True)
        save_path = os.path.join(config.DB_PATH, f"{face_name}.pkl")
        with open(save_path, "wb") as f:
            pickle.dump(embedding, f)
        return save_path

    def _save_rfid_mapping(self, rfid_uid: str, face_name: str) -> str:
        rfid_db_path = os.path.normpath(os.path.join(config.DB_PATH, "..", "rfid_database.json"))
        db = {}

        if os.path.exists(rfid_db_path):
            try:
                with open(rfid_db_path, "r", encoding="utf-8") as f:
                    db = json.load(f)
            except Exception:
                db = {}

        db[rfid_uid] = face_name

        with open(rfid_db_path, "w", encoding="utf-8") as f:
            json.dump(db, f, indent=4)

        return rfid_db_path
    def _read_rfid_uid(self, timeout_seconds: float = RFID_TIMEOUT_SECONDS) -> str:
        mock_uid = os.getenv("MOCK_RFID_UID", "").strip()
        if mock_uid:
            print(f"[PI] Using MOCK_RFID_UID={mock_uid}")
            return mock_uid

        if self.rfid_reader is None:
            raise RuntimeError("RFID reader not initialized and MOCK_RFID_UID not set")

        print("[PI] Waiting for RFID card tap...")
        start = time.time()

        while time.time() - start < timeout_seconds:
            try:
                if hasattr(self.rfid_reader, "read_no_block"):
                    result = self.rfid_reader.read_no_block()
                    card_id = result[0] if isinstance(result, tuple) else result
                    if card_id:
                        return str(card_id)

                elif hasattr(self.rfid_reader, "read_id_no_block"):
                    card_id = self.rfid_reader.read_id_no_block()
                    if card_id:
                        return str(card_id)

                elif hasattr(self.rfid_reader, "read"):
                    result = self.rfid_reader.read()
                    card_id = result[0] if isinstance(result, tuple) else result
                    if card_id:
                        return str(card_id)

            except Exception:
                pass

            time.sleep(0.2)

        raise RuntimeError("Timed out waiting for RFID card")
    def fetch_task(self) -> Optional[dict]:
        response = self.session.get(
            f"{BACKEND_BASE}/device/enrollment-task",
            headers=self.headers,
            params={"device_name": DEVICE_NAME},
            timeout=10,
        )
        response.raise_for_status()
        return response.json().get("task")

    def report_result(
        self,
        job_id: str,
        employee_id: str,
        face_name: str,
        success: bool,
        error: Optional[str] = None,
        rfid_uid: Optional[str] = None,
    ) -> None:
        payload = {
            "job_id": job_id,
            "employee_id": employee_id,
            "face_name": face_name,
            "success": success,
            "error": error,
            "device_name": DEVICE_NAME,
            "rfid_uid": rfid_uid,
        }
        response = self.session.post(
            f"{BACKEND_BASE}/device/enrollment-result",
            headers={**self.headers, "Content-Type": "application/json"},
            json=payload,
            timeout=15,
        )
        response.raise_for_status()

    def submit_access_attempt(self, card_id: str, face_name: Optional[str]) -> dict:
        response = self.session.post(
            f"{BACKEND_BASE}/access/check",
            headers=self.headers,
            json={
                "card_id": card_id,
                "face_name": face_name,
                "device_ip": DEVICE_NAME,
            },
            timeout=10,
        )
        response.raise_for_status()
        return response.json()
    def handle_task(self, task: dict) -> None:
        print(f"[PI] Starting enrollment job {task['jobId']} for {task['employeeId']} ({task['faceName']})")
        self._led_scanning()

        try:
            print("[PI] Waiting for motion before enrollment capture...")
            motion_start = time.time()
            while time.time() - motion_start < MAX_CAPTURE_SECONDS:
                if self._motion_detected():
                    break
                time.sleep(0.1)

            embedding = self._capture_embedding()
            save_path = self._save_embedding(task["faceName"], embedding)
            print(f"[PI] Saved face embedding to {save_path}")

            rfid_uid = self._read_rfid_uid()
            print(f"[PI] Captured RFID UID: {rfid_uid}")

            db_path = self._save_rfid_mapping(rfid_uid, task["faceName"])
            print(f"[PI] Synchronized new user to local RFID database: {db_path}")

            # force recognizer to reload next time
            self.recognizer.load_users()

            self.report_result(
                task["jobId"],
                task["employeeId"],
                task["faceName"],
                True,
                rfid_uid=rfid_uid,
            )
            self._led_access_granted()
            time.sleep(1.0)

        except Exception as exc:
            print(f"[PI] Enrollment failed: {exc}")
            self.report_result(
                task["jobId"],
                task["employeeId"],
                task["faceName"],
                False,
                error=str(exc),
            )
            self._led_access_denied()
            time.sleep(1.0)

        finally:
            self._lock_door()
            self._led_idle_locked()
    def _grant_access_sequence(self) -> None:
        print("[PI] Access approved. Unlocking door.")
        self._unlock_door()
        self._led_access_granted()

        unlock_started = time.time()
        door_opened = False

        # Wait for door to open
        while time.time() - unlock_started < DOOR_OPEN_TIMEOUT_SECONDS:
            if self._door_is_open():
                door_opened = True
                print("[PI] Door opened.")
                break
            time.sleep(0.1)

        if door_opened:
            close_wait_start = time.time()
            while time.time() - close_wait_start < DOOR_CLOSE_TIMEOUT_SECONDS:
                if not self._door_is_open():
                    print("[PI] Door closed.")
                    break
                time.sleep(0.1)
        else:
            print("[PI] Door did not open before timeout.")

        elapsed = time.time() - unlock_started
        remaining = max(0.0, DOOR_UNLOCK_SECONDS - elapsed)
        if remaining > 0:
            time.sleep(remaining)

        self._lock_door()
        self._led_idle_locked()
        print("[PI] Door re-locked.")

    def handle_access_cycle(self) -> None:
        now = time.time()
        if now - self.last_access_attempt_at < POST_ACCESS_COOLDOWN_SECONDS:
            return

        if self._door_is_open():
            return

        if not self._motion_detected():
            return

        self.last_motion_at = now
        self.last_access_attempt_at = now
        self._led_scanning()

        print("[PI] Motion detected. Starting access verification...")

        face_name = self._recognize_face_for_access(timeout_seconds=ACCESS_FACE_WINDOW_SECONDS)
        if face_name:
            print(f"[PI] Face candidate: {face_name}")
        else:
            print("[PI] No face recognized during access window.")

        try:
            card_id = self._read_rfid_uid(timeout_seconds=RFID_TIMEOUT_SECONDS)
            print(f"[PI] RFID card read: {card_id}")
        except Exception as exc:
            print(f"[PI] RFID read failed: {exc}")
            self._led_access_denied()
            time.sleep(1.0)
            self._led_idle_locked()
            return

        try:
            result = self.submit_access_attempt(card_id=card_id, face_name=face_name)
            approved = bool(result.get("approved"))

            if approved:
                self._grant_access_sequence()
            else:
                reason = result.get("reason", "Denied")
                print(f"[PI] Access denied: {reason}")
                self._led_access_denied()
                time.sleep(1.0)
                self._led_idle_locked()

        except Exception as exc:
            print(f"[PI] Access check failed: {exc}")
            self._led_access_denied()
            time.sleep(1.0)
            self._led_idle_locked()
    def run_forever(self) -> None:
        print(f"[PI] Agent running. Backend={BACKEND_BASE} Device={DEVICE_NAME}")
        self._lock_door()
        self._led_idle_locked()

        while True:
            try:
                task = self.fetch_task()
                if task:
                    self.handle_task(task)
                    continue
                self.handle_access_cycle()
                time.sleep(ACCESS_LOOP_SLEEP_SECONDS)

            except KeyboardInterrupt:
                raise
            except Exception as exc:
                print(f"[PI] Main loop error: {exc}")
                self._lock_door()
                self._led_idle_locked()
                time.sleep(POLL_INTERVAL_SECONDS)

    def cleanup(self) -> None:
        try:
            if hasattr(self.camera, "release"):
                self.camera.release()
        except Exception:
            pass

        try:
            self._lock_door()
            self._led_idle_locked()
        except Exception:
            pass

        try:
            if self.GPIO:
                self.GPIO.cleanup()
        except Exception:
            pass


if __name__ == "__main__":
    agent = PiAgent()
    try:
        agent.run_forever()
    finally:
        agent.cleanup()
