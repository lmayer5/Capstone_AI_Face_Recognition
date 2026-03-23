import cv2
import time
import numpy as np
from src.detector import FaceDetector
from src.recognizer import FaceIdentifier
from src.database import EventLogger
from src.hardware import DoorLock
from src.camera import get_camera
from src.async_utils import FaceRecognitionThread
import RPi.GPIO as GPIO
import evdev
import select
import config
import os
import json
from pi_agent import submit_access_attempt

def get_user_database():
    """Loads the RFID database dynamically from disk."""
    rfid_db_path = os.path.join(config.DB_PATH, "..", "rfid_database.json")
    if not os.path.exists(rfid_db_path):
        # Create a default database for backward compatibility
        default_db = {
            "0007649730": "Shiv",  # Card ID #1
            "0007655046": "Luke"   # Card ID #2
        }
        try:
            os.makedirs(os.path.dirname(rfid_db_path), exist_ok=True)
            with open(rfid_db_path, "w") as f:
                json.dump(default_db, f, indent=4)
        except Exception:
            pass
        return default_db
        
    try:
        with open(rfid_db_path, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"[ERROR] Could not load RFID database: {e}")
        return {}

# ---------------------------------------------------------
# 🧰 THE USB RFID HELPER (Translates keyboard clicks to an ID)
# ---------------------------------------------------------
class UsbRfidReader:
    def __init__(self):
        self.device = None
        self.barcode = ""
        # Map the weird USB key codes back into normal numbers
        self.keys = {
            'KEY_0': '0', 'KEY_1': '1', 'KEY_2': '2', 'KEY_3': '3',
            'KEY_4': '4', 'KEY_5': '5', 'KEY_6': '6', 'KEY_7': '7',
            'KEY_8': '8', 'KEY_9': '9'
        }

        # Automatically hunt for the scanner by its name so it survives reboots!
        for path in evdev.list_devices():
            dev = evdev.InputDevice(path)
            if "RFID" in dev.name:
                self.device = dev
                self.device.grab()  # 🛑 Stop the scanner from typing into the terminal
                print(f"✅ RFID Scanner locked and loaded at {path}")
                break
                
        if not self.device:
            print("⚠️ WARNING: RFID Scanner not found! Check the USB port.")

    def read_id_no_block(self):
        if not self.device: return None

        # 👁️ THE QUICK GLANCE: Check the USB port for 0.0 seconds. 
        # If nothing is there, instantly move on so the camera doesn't freeze.
        r, _, _ = select.select([self.device.fd], [], [], 0.0)
        
        if r:
            for event in self.device.read():
                # Value 1 means a key was pressed down
                if event.type == evdev.ecodes.EV_KEY and event.value == 1: 
                    key_name = evdev.ecodes.KEY[event.code]
                    
                    if key_name == 'KEY_ENTER':
                        # The scanner hit Enter! The card reading is complete.
                        final_id = self.barcode
                        self.barcode = "" # Clear it for the next person
                        return final_id
                    elif key_name in self.keys:
                        # Add the number to our growing ID string
                        self.barcode += self.keys[key_name]
        return None

    def release(self):
        # Let go of the USB port when the program closes
        if self.device:
            self.device.ungrab()


# ---------------------------------------------------------
# 🚀 THE MAIN CAPSTONE LOOP
# ---------------------------------------------------------

def main():
    # Initialize components
    detector = FaceDetector()
    recognizer = FaceIdentifier()
    logger = EventLogger()
    door_lock = DoorLock()
    rfid_reader = UsbRfidReader() #RFID reader
    
    # Initialize and start Background Thread
    recog_thread = FaceRecognitionThread(recognizer, door_lock, logger)
    recog_thread.start()

    # 🧠"Short Term" Memory Variables
    recent_face_name = None
    recent_face_time = 0.0
    
    # State tracking
    cap = None
    camera_active = False
    last_activity_time = time.time()
    
    pending_rfid_user = None
    pending_rfid_time = 0.0
    pending_rfid_card = None
    RFID_FACE_TIMEOUT = 15.0 # Seconds to show face after swiping
    
    unlock_expiry_time = None
    door_was_opened_while_unlocked = False

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
            if cap: 
                cap.release()
                cap = None
            camera_active = False
            door_lock.set_unknown() # Red LED idle state

    print("Starting Main Loop (Threaded)...")
    print("Press 'q' to quit." if not config.HEADLESS else "Press Ctrl+C to quit.")

    try:
        print("🟢 Capstone System Active! Press Ctrl+C to shut down.")
        
        while True:
            # 1. 🚶 Check PIR Motion Sensor
            if door_lock.is_motion_detected():
                wake_camera()

            # 2. 💳 Check RFID (Continuous)
            card_id = rfid_reader.read_id_no_block()
            if card_id:
                print(f"\n💳 Card Swiped! ID: {card_id}")
                wake_camera() # Wake camera immediately
                
                USER_DATABASE = get_user_database()
                if card_id in USER_DATABASE:
                    expected_name = USER_DATABASE[card_id]
                    print(f"✅ Valid Card ({expected_name}). Please look at the camera for authentication.")
                    
                    pending_rfid_user = expected_name
                    pending_rfid_time = time.time()
                    pending_rfid_card = card_id
                    
                    # 🌐 Web App Webhook: Send Tap In log
                    try:
                        submit_access_attempt(card_id, f"Pending Face Scan: {expected_name}")
                    except Exception as e:
                        print(f"[PI] Web App Log Warning: {e}")
                else:
                    print("❌ Unknown Card! Access Denied.")
                    try:
                        submit_access_attempt(card_id, "Unknown Card / Denied")
                    except Exception: pass

            # 3. 💤 Check Auto-Sleep Timeout
            if camera_active and (time.time() - last_activity_time > config.CAMERA_IDLE_TIMEOUT) and door_lock.is_locked:
                sleep_camera()
                
            # 4. 👁️ Handle Camera Frame or Sleep UI
            frame = None
            if camera_active and cap:
                success, f = cap.read()
                if success:
                    frame = f
                    # Process frame
                    faces_bboxes = detector.detect(frame)
                    
                    # If faces found, update activity time so it stays awake!
                    if faces_bboxes:
                        last_activity_time = time.time()
                    
                    if faces_bboxes and not recog_thread.input_queue.full():
                        door_lock.set_scanning()
                        target_face = max(faces_bboxes, key=lambda b: b[2] * b[3])
                        (x, y, w, h) = target_face
                        H, W, _ = frame.shape
                        x, y, w, h = max(0, x), max(0, y), min(w, W - x), min(h, H - y)
                        face_crop = frame[y:y+h, x:x+w]
                        if face_crop.size > 0:
                            recog_thread.input_queue.put(face_crop)

                    # Update UI 
                    if not config.HEADLESS:
                        for (x, y, w, h) in faces_bboxes:
                            name = recog_thread.current_user_name
                            # 🧠 Remember the face
                            if name != "Unknown" and name != "Scanning...":
                                recent_face_name = name
                                recent_face_time = time.time()

                            color = (0, 255, 0) if name != "Unknown" and name != "Scanning..." else (0, 0, 255)
                            if name == "Scanning...": color = (255, 255, 0)
                            cv2.rectangle(frame, (x, y), (x+w, y+h), color, 2)
                            cv2.putText(frame, name, (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
                else:
                    # If read failed, gracefully sleep to recover
                    sleep_camera()
            else:
                # Sleep UI
                if not config.HEADLESS:
                    frame = np.zeros((480, 640, 3), dtype=np.uint8)
                    cv2.putText(frame, "SYSTEM IDLE", (200, 220), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (100, 100, 100), 2)
                    cv2.putText(frame, "Waiting for PIR Motion or RFID...", (120, 260), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (150, 150, 150), 2)

            # 5. 🔓 Lock Logic & Reversed 2FA (RFID -> Face) Logic
            # Only process 2FA match if door is LOCKED
            if door_lock.is_locked:
                if pending_rfid_user:
                    # Timeout check
                    if time.time() - pending_rfid_time > RFID_FACE_TIMEOUT:
                        print(f"❌ 2FA Timeout! No matching face for {pending_rfid_user} seen.")
                        pending_rfid_user = None
                    else:
                        # Match check
                        if recent_face_name == pending_rfid_user and (time.time() - recent_face_time <= RFID_FACE_TIMEOUT):
                            print(f"🔓 2FA SUCCESS! Face ({recent_face_name}) matches Card. Opening door...")
                            door_lock.unlock()
                            
                            # 🌐 Web App Webhook: Send Success Log
                            try:
                                submit_access_attempt(pending_rfid_card, recent_face_name) 
                            except Exception: pass
                            
                            pending_rfid_user = None
                            recent_face_name = None
                            door_was_opened_while_unlocked = False
                            unlock_expiry_time = time.time() + config.AUTO_LOCK_DELAY
            else:
                # Door is currently UNLOCKED
                if door_lock.is_door_open():
                    door_was_opened_while_unlocked = True
                    # Push back expiry so it doesn't lock while open
                    unlock_expiry_time = time.time() + config.AUTO_LOCK_DELAY
                    
                # If door opened and subsequently closed, or timer expires:
                if (door_was_opened_while_unlocked and not door_lock.is_door_open()) or (time.time() > unlock_expiry_time):
                    print("[SYSTEM] Door Secured (Closed or Timer Expired). Auto-locking.")
                    door_lock.lock()
                    unlock_expiry_time = None
                    door_was_opened_while_unlocked = False
                    
                    # Immediately power off camera as requested!
                    sleep_camera()

            # 6. Global Draw UI
            if not config.HEADLESS and frame is not None:
                # Global Status
                if not door_lock.is_locked:
                     rem = int(unlock_expiry_time - time.time()) if unlock_expiry_time else 0
                     cv2.putText(frame, f"ACCESS GRANTED ({rem}s)", (50, frame.shape[0] - 50), 
                            cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 3)

                if pending_rfid_user:
                     rem = int(RFID_FACE_TIMEOUT - (time.time() - pending_rfid_time))
                     cv2.putText(frame, f"WAITING FOR FACE: {pending_rfid_user} ({rem}s)", (50, frame.shape[0] - 80), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)

                door_status_text = "DOOR: OPEN" if door_lock.is_door_open() else "DOOR: CLOSED"
                door_status_color = (0, 0, 255) if door_lock.is_door_open() else (255, 255, 255)
                cv2.putText(frame, door_status_text, (frame.shape[1] - 200, 30), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, door_status_color, 2)

                cv2.imshow('Face Recognition System', frame)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
            elif config.HEADLESS:
                time.sleep(0.01)

    except KeyboardInterrupt:
        print("\nKeyboard interrupt received.")
    finally:
        print("🧹 Turning off Camera and GPIO pins...")
        recog_thread.stop()
        if cap: cap.release()
        if not config.HEADLESS:
            cv2.destroyAllWindows()
        logger.close()
        door_lock.cleanup()
        GPIO.cleanup()
        rfid_reader.release()

if __name__ == "__main__":
    main()
