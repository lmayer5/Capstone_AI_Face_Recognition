from __future__ import annotations

import os
import pickle
import sys
import time
from typing import Optional

import requests

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "pi_project", "Capstone_AI_Face_Recognition-main")
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.camera import get_camera
from src.detector import FaceDetector
from src.recognizer import FaceIdentifier
import config

BACKEND_BASE = os.getenv("BACKEND_BASE", "http://localhost:8080")
DEVICE_TOKEN = os.getenv("DEVICE_TOKEN", "")
DEVICE_NAME = os.getenv("PI_DEVICE_NAME", "raspberry-pi-1")
POLL_INTERVAL_SECONDS = float(os.getenv("ENROLLMENT_POLL_INTERVAL", "2.0"))
MAX_CAPTURE_SECONDS = float(os.getenv("ENROLLMENT_CAPTURE_TIMEOUT", "20.0"))
REQUIRED_STABLE_FRAMES = int(os.getenv("ENROLLMENT_STABLE_FRAMES", "10"))
RFID_TIMEOUT_SECONDS = float(os.getenv("RFID_CAPTURE_TIMEOUT", "15.0"))


class PiEnrollmentAgent:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.detector = FaceDetector()
        self.recognizer = FaceIdentifier()
        self.camera = get_camera()
        self.headers = {"x-device-token": DEVICE_TOKEN} if DEVICE_TOKEN else {}
        self.rfid_reader = self._init_rfid_reader()

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

    def _capture_embedding(self):
        print("[PI] Capturing face embedding...")
        start = time.time()
        stable = 0
        embedding = None

        while time.time() - start < MAX_CAPTURE_SECONDS:
            frame = self.camera.read()
            if frame is None:
                time.sleep(0.05)
                continue

            faces = self.detector.detect(frame)
            if len(faces) != 1:
                stable = 0
                time.sleep(0.05)
                continue

            emb = self.recognizer.get_embedding(frame, faces[0])
            if emb is None:
                stable = 0
                time.sleep(0.05)
                continue

            embedding = emb
            stable += 1
            if stable >= REQUIRED_STABLE_FRAMES:
                print("[PI] Stable face capture complete.")
                return embedding

            time.sleep(0.05)

        raise RuntimeError("Timed out waiting for a stable single-face capture")

    def _save_embedding(self, face_name: str, embedding) -> str:
        os.makedirs(config.DB_PATH, exist_ok=True)
        save_path = os.path.join(config.DB_PATH, f"{face_name}.pkl")
        with open(save_path, "wb") as f:
            pickle.dump(embedding, f)
        return save_path

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
                    if isinstance(result, tuple):
                        card_id = result[0]
                    else:
                        card_id = result
                    if card_id:
                        return str(card_id)
                elif hasattr(self.rfid_reader, "read_id_no_block"):
                    card_id = self.rfid_reader.read_id_no_block()
                    if card_id:
                        return str(card_id)
                elif hasattr(self.rfid_reader, "read"):
                    result = self.rfid_reader.read()
                    if isinstance(result, tuple):
                        card_id = result[0]
                    else:
                        card_id = result
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

    def handle_task(self, task: dict) -> None:
        print(f"[PI] Starting enrollment job {task['jobId']} for {task['employeeId']} ({task['faceName']})")
        try:
            embedding = self._capture_embedding()
            save_path = self._save_embedding(task["faceName"], embedding)
            print(f"[PI] Saved face embedding to {save_path}")
            rfid_uid = self._read_rfid_uid()
            print(f"[PI] Captured RFID UID: {rfid_uid}")
            self.report_result(task["jobId"], task["employeeId"], task["faceName"], True, rfid_uid=rfid_uid)
        except Exception as exc:
            print(f"[PI] Enrollment failed: {exc}")
            self.report_result(task["jobId"], task["employeeId"], task["faceName"], False, error=str(exc))

    def run_forever(self) -> None:
        print(f"[PI] Agent running. Backend={BACKEND_BASE} Device={DEVICE_NAME}")
        while True:
            try:
                task = self.fetch_task()
                if task:
                    self.handle_task(task)
                else:
                    time.sleep(POLL_INTERVAL_SECONDS)
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                print(f"[PI] Loop error: {exc}")
                time.sleep(POLL_INTERVAL_SECONDS)

    def cleanup(self) -> None:
        try:
            if hasattr(self.camera, "release"):
                self.camera.release()
        except Exception:
            pass

        try:
            import RPi.GPIO as GPIO  # type: ignore
            GPIO.cleanup()
        except Exception:
            pass


def submit_access_attempt(card_id: str, face_name: Optional[str]) -> dict:
    headers = {"x-device-token": DEVICE_TOKEN} if DEVICE_TOKEN else {}
    response = requests.post(
        f"{BACKEND_BASE}/access/check",
        headers=headers,
        json={"card_id": card_id, "face_name": face_name, "device_ip": DEVICE_NAME},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


if __name__ == "__main__":
    agent = PiEnrollmentAgent()
    try:
        agent.run_forever()
    finally:
        agent.cleanup()
