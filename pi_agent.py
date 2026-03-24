from __future__ import annotations

import json
import os
import pickle
import time
from typing import Any, Optional, Tuple

import requests
import config

from src.detector import FaceDetector
from src.recognizer import FaceIdentifier


BACKEND_BASE = os.getenv("BACKEND_BASE", "http://10.0.0.11:8080").rstrip("/")
DEVICE_TOKEN = os.getenv("DEVICE_TOKEN", "")
DEVICE_NAME = os.getenv("PI_DEVICE_NAME", "raspberry-pi-1")

ENROLLMENT_POLL_INTERVAL = float(os.getenv("ENROLLMENT_POLL_INTERVAL", "2.0"))
ENROLLMENT_CAPTURE_TIMEOUT = float(os.getenv("ENROLLMENT_CAPTURE_TIMEOUT", "20.0"))
ENROLLMENT_STABLE_FRAMES = int(os.getenv("ENROLLMENT_STABLE_FRAMES", "8"))
RFID_CAPTURE_TIMEOUT = float(os.getenv("RFID_CAPTURE_TIMEOUT", "15.0"))
FACE_CROP_PADDING = int(os.getenv("FACE_CROP_PADDING", "20"))

_session = requests.Session()
_headers = {"x-device-token": DEVICE_TOKEN} if DEVICE_TOKEN else {}


# -------------------------------------------------------------------
# Generic backend helpers used by main.py
# -------------------------------------------------------------------

def submit_access_attempt(card_id: str, face_name: Optional[str]) -> dict:
    """
    Used by main.py during live access attempts.
    Keeps compatibility with:
        from pi_agent import submit_access_attempt
    """
    response = _session.post(
        f"{BACKEND_BASE}/access/check",
        headers=_headers,
        json={
            "card_id": card_id,
            "face_name": face_name,
            "device_ip": DEVICE_NAME,
        },
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def fetch_enrollment_task() -> Optional[dict]:
    """
    Pull the next queued enrollment task from the backend.
    Returns the 'task' object or None.
    """
    response = _session.get(
        f"{BACKEND_BASE}/device/enrollment-task",
        headers=_headers,
        params={"device_name": DEVICE_NAME},
        timeout=10,
    )
    response.raise_for_status()
    return response.json().get("task")


def report_enrollment_result(
    job_id: str,
    employee_id: str,
    face_name: str,
    success: bool,
    error: Optional[str] = None,
    rfid_uid: Optional[str] = None,
) -> dict:
    """
    Report enrollment completion back to the backend.
    """
    payload = {
        "job_id": job_id,
        "employee_id": employee_id,
        "face_name": face_name,
        "success": success,
        "error": error,
        "device_name": DEVICE_NAME,
        "rfid_uid": rfid_uid,
    }

    response = _session.post(
        f"{BACKEND_BASE}/device/enrollment-result",
        headers={**_headers, "Content-Type": "application/json"},
        json=payload,
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


# -------------------------------------------------------------------
# Local DB helpers
# -------------------------------------------------------------------

def get_local_rfid_db_path() -> str:
    return os.path.join(config.DB_PATH, "rfid_database.json")


def load_local_rfid_database() -> dict:
    rfid_db_path = get_local_rfid_db_path()

    if not os.path.exists(rfid_db_path):
        return {}

    try:
        with open(rfid_db_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_local_rfid_database(data: dict) -> str:
    os.makedirs(config.DB_PATH, exist_ok=True)
    rfid_db_path = get_local_rfid_db_path()

    with open(rfid_db_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

    return rfid_db_path


def save_local_rfid_mapping(rfid_uid: str, face_name: str) -> str:
    db = load_local_rfid_database()
    db[str(rfid_uid)] = str(face_name)
    return save_local_rfid_database(db)


def save_face_embedding(face_name: str, embedding: Any) -> str:
    os.makedirs(config.DB_PATH, exist_ok=True)
    save_path = os.path.join(config.DB_PATH, f"{face_name}.pkl")
    with open(save_path, "wb") as f:
        pickle.dump(embedding, f)
    return save_path


# -------------------------------------------------------------------
# Camera / face helpers
# -------------------------------------------------------------------

def normalize_camera_read_result(result: Any) -> Tuple[bool, Optional[Any]]:
    """
    Supports both camera APIs:
      - cap.read() -> (ok, frame)
      - custom_camera.read() -> frame
    """
    if isinstance(result, tuple) and len(result) == 2:
        ok, frame = result
        return bool(ok), frame

    if result is None:
        return False, None

    return True, result


def crop_face(frame, face_box, padding: int = FACE_CROP_PADDING):
    x, y, w, h = face_box

    x1 = max(0, x - padding)
    y1 = max(0, y - padding)
    x2 = min(frame.shape[1], x + w + padding)
    y2 = min(frame.shape[0], y + h + padding)

    crop = frame[y1:y2, x1:x2]
    if crop is None or crop.size == 0:
        return None
    return crop


def capture_stable_embedding_from_camera(
    camera,
    detector: Optional[FaceDetector] = None,
    recognizer: Optional[FaceIdentifier] = None,
    timeout_seconds: float = ENROLLMENT_CAPTURE_TIMEOUT,
    stable_frames_required: int = ENROLLMENT_STABLE_FRAMES,
):
    """
    Used for enrollment capture only.
    Fixes the old OpenCV tuple issue by normalizing camera.read() output
    before passing the frame to detector.detect().
    """
    detector = detector or FaceDetector()
    recognizer = recognizer or FaceIdentifier()

    start = time.time()
    stable = 0
    embedding = None

    while time.time() - start < timeout_seconds:
        ok, frame = normalize_camera_read_result(camera.read())
        if not ok or frame is None:
            time.sleep(0.05)
            continue

        faces = detector.detect(frame)
        if len(faces) != 1:
            stable = 0
            time.sleep(0.05)
            continue

        face_crop = crop_face(frame, faces[0])
        if face_crop is None:
            stable = 0
            time.sleep(0.05)
            continue

        emb = recognizer.get_embedding(face_crop)
        if emb is None:
            stable = 0
            time.sleep(0.05)
            continue

        embedding = emb
        stable += 1

        if stable >= stable_frames_required:
            return embedding

        time.sleep(0.05)

    raise RuntimeError("Timed out waiting for a stable single-face capture")


# -------------------------------------------------------------------
# RFID helper
# -------------------------------------------------------------------

def read_rfid_uid(reader, timeout_seconds: float = RFID_CAPTURE_TIMEOUT) -> str:
    """
    Generic RFID helper for enrollment flows.
    Works with:
      - read_no_block()
      - read_id_no_block()
      - read()
    """
    mock_uid = os.getenv("MOCK_RFID_UID", "").strip()
    if mock_uid:
        return mock_uid

    if reader is None:
        raise RuntimeError("RFID reader not initialized and MOCK_RFID_UID not set")

    start = time.time()
    while time.time() - start < timeout_seconds:
        try:
            if hasattr(reader, "read_no_block"):
                result = reader.read_no_block()
                card_id = result[0] if isinstance(result, tuple) else result
                if card_id:
                    return str(card_id)

            elif hasattr(reader, "read_id_no_block"):
                card_id = reader.read_id_no_block()
                if card_id:
                    return str(card_id)

            elif hasattr(reader, "read"):
                result = reader.read()
                card_id = result[0] if isinstance(result, tuple) else result
                if card_id:
                    return str(card_id)

        except Exception:
            pass

        time.sleep(0.2)

    raise RuntimeError("Timed out waiting for RFID card")


# -------------------------------------------------------------------
# Enrollment runner for use from main.py
# -------------------------------------------------------------------

def process_one_enrollment_task(camera, rfid_reader) -> bool:
    """
    Helper function that main.py can call periodically.
    Returns True if a task was processed, otherwise False.

    Flow:
      1. fetch task from backend
      2. capture stable face embedding from provided camera
      3. save embedding locally
      4. read RFID from provided reader
      5. save local RFID mapping
      6. report result to backend
    """
    task = fetch_enrollment_task()
    if not task:
        return False

    detector = FaceDetector()
    recognizer = FaceIdentifier()

    try:
        print(f"[PI] Starting enrollment job {task['jobId']} for {task['employeeId']} ({task['faceName']})")

        embedding = capture_stable_embedding_from_camera(
            camera=camera,
            detector=detector,
            recognizer=recognizer,
        )

        save_path = save_face_embedding(task["faceName"], embedding)
        print(f"[PI] Saved face embedding to {save_path}")

        rfid_uid = read_rfid_uid(rfid_reader)
        print(f"[PI] Captured RFID UID: {rfid_uid}")

        db_path = save_local_rfid_mapping(rfid_uid, task["faceName"])
        print(f"[PI] Updated local RFID database: {db_path}")

        try:
            recognizer.load_users()
        except Exception:
            pass

        report_enrollment_result(
            job_id=task["jobId"],
            employee_id=task["employeeId"],
            face_name=task["faceName"],
            success=True,
            rfid_uid=rfid_uid,
        )

        return True

    except Exception as exc:
        print(f"[PI] Enrollment failed: {exc}")

        try:
            report_enrollment_result(
                job_id=task["jobId"],
                employee_id=task["employeeId"],
                face_name=task["faceName"],
                success=False,
                error=str(exc),
            )
        except Exception as report_exc:
            print(f"[PI] Failed to report enrollment failure: {report_exc}")

        return True
