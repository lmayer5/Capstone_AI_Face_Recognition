import cv2
import time
import numpy as np
from src.detector import FaceDetector
from src.recognizer import FaceIdentifier
from src.database import EventLogger
from src.hardware import DoorLock
from src.camera import get_camera
from src.async_utils import FaceRecognitionThread
import config
import os
import json
import evdev
import select

from pi_agent import (
    submit_access_attempt,
    process_one_enrollment_task,
    fetch_enrollment_task,
)


def get_user_database():
    """Loads the RFID database dynamically from disk."""
    rfid_db_path = os.path.join(config.DB_PATH, ".", "rfid_database.json")
    if not os.path.exists(rfid_db_path):
        default_db = {
            "0007649730": "Shiv",
            "0007655046": "Luke",
        }
        try:
            os.makedirs(os.path.dirname(rfid_db_path), exist_ok=True)
            with open(rfid_db_path, "w", encoding="utf-8") as f:
                json.dump(default_db, f, indent=4)
        except Exception:
            pass
        return default_db

    try:
        with open(rfid_db_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"[ERROR] Could not load RFID database: {e}")
        return {}


class UsbRfidReader:
    def __init__(self):
        self.device = None
        self.barcode = ""
        self.keys = {
            "KEY_0": "0", "KEY_1": "1", "KEY_2": "2", "KEY_3": "3",
            "KEY_4": "4", "KEY_5": "5", "KEY_6": "6", "KEY_7": "7",
            "KEY_8": "8", "KEY_9": "9",
        }

        for path in evdev.list_devices():
            dev = evdev.InputDevice(path)
            if "RFID" in dev.name:
                self.device = dev
                self.device.grab()
                print(f"✅ RFID Scanner locked and loaded at {path}")
                break

        if not self.device:
            print("⚠️ WARNING: RFID Scanner not found! Check the USB port.")

    def read_id_no_block(self):
        if not self.device:
            return None

        r, _, _ = select.select([self.device.fd], [], [], 0.0)
        if r:
            for event in self.device.read():
                if event.type == evdev.ecodes.EV_KEY and event.value == 1:
                    key_name = evdev.ecodes.KEY[event.code]

                    if key_name == "KEY_ENTER":
                        final_id = self.barcode
                        self.barcode = ""
                        return final_id
                    elif key_name in self.keys:
                        self.barcode += self.keys[key_name]

        return None

    def release(self):
        if self.device:
            try:
                self.device.ungrab()
            except Exception:
                pass


def main():
    detector = FaceDetector()
    recognizer = FaceIdentifier()
    logger = EventLogger()
    door_lock = DoorLock()
    rfid_reader = UsbRfidReader()

    recog_thread = FaceRecognitionThread(recognizer, door_lock, logger)
    recog_thread.start()

    recent_face_name = None
    recent_face_time = 0.0

    cap = None
    camera_active = False
    last_activity_time = time.time()

    pending_rfid_user = None
    pending_rfid_time = 0.0
    pending_rfid_card = None

    RFID_FACE_TIMEOUT = 15.0
    unlock_expiry_time = None
    door_was_opened_while_unlocked = False

    # Enrollment state
    ENROLLMENT_POLL_SECONDS = 2.0
    last_enrollment_poll = 0.0
    enrollment_mode = False
    active_enrollment_task = None

    def wake_camera():
        nonlocal cap, camera_active, last_activity_time
        if not camera_active:
            print("[SYSTEM] Motion/RFID detected! Waking up camera...")
            cap = get_camera()
            camera_active = True
        last_activity_time = time.time()

    def sleep_camera():
        nonlocal cap, camera_active
        if camera_active:
            print("[SYSTEM] Putting camera to sleep (No activity or Door Secured)...")
            try:
                if cap:
                    cap.release()
            except Exception:
                pass
            cap = None
            camera_active = False
            try:
                door_lock.set_unknown()
            except Exception:
                pass

    def clear_pending_rfid():
        nonlocal pending_rfid_user, pending_rfid_time, pending_rfid_card
        pending_rfid_user = None
        pending_rfid_time = 0.0
        pending_rfid_card = None

    print("Starting Main Loop (Threaded)...")
    print("Press 'q' to quit." if not config.HEADLESS else "Press Ctrl+C to quit.")

    try:
        print("🟢 Capstone System Active! Press Ctrl+C to shut down.")

        while True:
            now = time.time()

            # 1. Enrollment polling
            if not enrollment_mode and (now - last_enrollment_poll >= ENROLLMENT_POLL_SECONDS):
                last_enrollment_poll = now
                try:
                    task = fetch_enrollment_task()
                    if task:
                        active_enrollment_task = task
                        enrollment_mode = True
                        print(
                            f"[ENROLLMENT] Task received: {task['jobId']} "
                            f"for {task['employeeId']} ({task['faceName']})"
                        )
                        wake_camera()

                        # Clear any active access state before enrollment
                        clear_pending_rfid()
                        recent_face_name = None
                        recent_face_time = 0.0
                except Exception as e:
                    print(f"[ENROLLMENT] Poll warning: {e}")

            # 2. Run enrollment if needed
            if enrollment_mode:
                try:
                    if not camera_active or cap is None:
                        wake_camera()

                    print("[ENROLLMENT] Processing enrollment job...")
                    processed = process_one_enrollment_task(cap, rfid_reader)

                    if processed:
                        print("[ENROLLMENT] Task processing finished.")
                    else:
                        print("[ENROLLMENT] No task processed.")
                except Exception as e:
                    print(f"[ENROLLMENT] Processing error: {e}")
                finally:
                    active_enrollment_task = None
                    enrollment_mode = False
                    recent_face_name = None
                    recent_face_time = 0.0
                    clear_pending_rfid()
                    last_activity_time = time.time()

                time.sleep(0.2)
                continue

            # 3. PIR motion sensor
            try:
                if door_lock.is_motion_detected():
                    wake_camera()
            except Exception as e:
                print(f"[PIR] Motion sensor warning: {e}")

            # 4. RFID polling
            card_id = rfid_reader.read_id_no_block()
            if card_id:
                print(f"\n💳 Card Swiped! ID: {card_id}")
                wake_camera()

                user_database = get_user_database()
                if card_id in user_database:
                    expected_name = user_database[card_id]
                    print(f"✅ Valid Card ({expected_name}). Please look at the camera for authentication.")

                    pending_rfid_user = expected_name
                    pending_rfid_time = time.time()
                    pending_rfid_card = card_id

                    # Do not send fake face names to backend.
                    # Backend expects None or a real recognized name.
                else:
                    print("❌ Unknown Card! Access Denied.")
                    try:
                        result = submit_access_attempt(card_id, None)
                        print(f"[PI] Backend denied unknown RFID: {result}")
                    except Exception as e:
                        print(f"[PI] Web App Log Warning: {e}")

                    clear_pending_rfid()

            # 5. Auto-sleep timeout
            try:
                if (
                    camera_active
                    and (time.time() - last_activity_time > config.CAMERA_IDLE_TIMEOUT)
                    and door_lock.is_locked
                    and not pending_rfid_user
                ):
                    sleep_camera()
            except Exception as e:
                print(f"[CAMERA] Sleep warning: {e}")

            # 6. Handle camera frame / recognition
            frame = None
            if camera_active and cap:
                try:
                    read_result = cap.read()

                    if isinstance(read_result, tuple) and len(read_result) == 2:
                        success, frame_candidate = read_result
                    else:
                        success, frame_candidate = (read_result is not None), read_result

                    if success and frame_candidate is not None:
                        frame = frame_candidate
                        faces_bboxes = detector.detect(frame)

                        if faces_bboxes:
                            last_activity_time = time.time()

                        if faces_bboxes and not recog_thread.input_queue.full():
                            try:
                                door_lock.set_scanning()
                            except Exception:
                                pass

                            target_face = max(faces_bboxes, key=lambda b: b[2] * b[3])
                            (x, y, w, h) = target_face

                            H, W, _ = frame.shape
                            x = max(0, x)
                            y = max(0, y)
                            w = min(w, W - x)
                            h = min(h, H - y)

                            face_crop = frame[y:y + h, x:x + w]
                            if face_crop is not None and face_crop.size > 0:
                                recog_thread.input_queue.put(face_crop)

                        if not config.HEADLESS:
                            for (x, y, w, h) in faces_bboxes:
                                name = recog_thread.current_user_name

                                if name not in ("Unknown", "Scanning.", None):
                                    recent_face_name = name
                                    recent_face_time = time.time()

                                color = (0, 255, 0) if name not in ("Unknown", "Scanning.", None) else (0, 0, 255)
                                if name == "Scanning.":
                                    color = (255, 255, 0)

                                cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
                                cv2.putText(
                                    frame,
                                    str(name),
                                    (x, y - 10),
                                    cv2.FONT_HERSHEY_SIMPLEX,
                                    0.5,
                                    color,
                                    2,
                                )
                    else:
                        sleep_camera()
                except Exception as e:
                    print(f"[CAMERA] Frame processing error: {e}")
                    sleep_camera()
            else:
                if not config.HEADLESS:
                    frame = np.zeros((480, 640, 3), dtype=np.uint8)
                    cv2.putText(frame, "SYSTEM IDLE", (200, 220), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (100, 100, 100), 2)
                    cv2.putText(frame, "Waiting for PIR Motion or RFID.", (120, 260), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (150, 150, 150), 2)

            # 7. Reversed 2FA logic (RFID -> Face)
            try:
                if door_lock.is_locked:
                    if pending_rfid_user:
                        if time.time() - pending_rfid_time > RFID_FACE_TIMEOUT:
                            print(f"❌ 2FA Timeout! No matching face for {pending_rfid_user} seen.")
                            clear_pending_rfid()
                        else:
                            if (
                                recent_face_name == pending_rfid_user
                                and (time.time() - recent_face_time <= RFID_FACE_TIMEOUT)
                            ):
                                print(f"🔓 2FA SUCCESS! Face ({recent_face_name}) matches Card. Opening door.")
                                door_lock.unlock()

                                try:
                                    submit_access_attempt(pending_rfid_card, recent_face_name)
                                except Exception as e:
                                    print(f"[PI] Web App Log Warning: {e}")

                                clear_pending_rfid()
                                recent_face_name = None
                                door_was_opened_while_unlocked = False
                                unlock_expiry_time = time.time() + config.AUTO_LOCK_DELAY

                else:
                    # Door currently unlocked
                    if door_lock.is_door_open():
                        door_was_opened_while_unlocked = True

                    if unlock_expiry_time is not None and time.time() >= unlock_expiry_time:
                        if door_was_opened_while_unlocked:
                            if not door_lock.is_door_open():
                                print("🔒 Door closed after access. Relocking.")
                                door_lock.lock()
                                unlock_expiry_time = None
                                door_was_opened_while_unlocked = False
                            else:
                                # Wait until the door closes
                                pass
                        else:
                            print("🔒 Unlock timeout elapsed without door open. Relocking.")
                            door_lock.lock()
                            unlock_expiry_time = None
                            door_was_opened_while_unlocked = False

            except Exception as e:
                print(f"[DOOR] Lock logic warning: {e}")

            # 8. UI display
            if not config.HEADLESS and frame is not None:
                try:
                    cv2.imshow("Capstone Door Lock System", frame)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break
                except Exception as e:
                    print(f"[UI] Display warning: {e}")

            time.sleep(0.01)

    except KeyboardInterrupt:
        print("\n🛑 Shutting down system...")

    finally:
        try:
            if cap:
                cap.release()
        except Exception:
            pass

        try:
            rfid_reader.release()
        except Exception:
            pass

        try:
            if not config.HEADLESS:
                cv2.destroyAllWindows()
        except Exception:
            pass

        try:
            recog_thread.stop()
        except Exception:
            pass

        try:
            door_lock.lock()
        except Exception:
            pass

        print("✅ System shutdown complete.")


if __name__ == "__main__":
    main()
