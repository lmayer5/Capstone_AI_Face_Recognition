import cv2
import time
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

    #RFID Card IDs (replace with your actual card IDs)
    USER_DATABASE = {
        "0007649730": "Shiv",  # Card ID #1
        "0007655046": "Luke"     # Card ID #2
    }
    # 🧠"Short Term" Memory Variables
    recent_face_name = None
    recent_face_time = 0.0
    MEMORY_WINDOW = 5.0  # How many seconds the Pi remembers a face
    # Use platform-aware camera
    cap = get_camera()
    
    # Lock Logic State
    unlock_expiry_time = None 
    
    print("Starting Main Loop (Threaded)...")
    print("Press 'q' to quit." if not config.HEADLESS else "Press Ctrl+C to quit.")

    try:
        print("🟢 Capstone System Active! Press Ctrl+C to shut down.")
        while True:
            # ----------------------------------------
            # 👁️ 1. THE AI CAMERA PART
            # ----------------------------------------
            success, frame = cap.read()
            # 0. Check Auto-Lock Logic
            # Detect if door was unlocked by thread
           # if not door_lock.is_locked:
           if not success: continue
                # If we haven't set a timer yet, set it now
                if unlock_expiry_time is None:
                    unlock_expiry_time = time.time() + config.AUTO_LOCK_DELAY
                    print("[SYSTEM] Face authenticated. Timer started, please scan RFID card within the next few seconds.")
                
                # Check expiry
                elif time.time() > unlock_expiry_time:
                    door_lock.lock()
                    unlock_expiry_time = None
                    print("[SYSTEM] Auto-locking door.")
            else:
                # Reset timer if locked
                unlock_expiry_time = None

            ret, frame = cap.read()
            if not ret:
                print("[ERROR] Failed to grab frame. Retrying...")
                time.sleep(0.1)
                continue
            
            # 1. Detection (Main Thread - Fast)
            start_det = time.time()
            faces_bboxes = detector.detect(frame)
            
            # 2. Delegate to Recognition Thread
            # Only send if thread is ready (queue not full) and we have a face
            if faces_bboxes and not recog_thread.input_queue.full():
                # Set scanning LED
                door_lock.set_scanning()
                
                # Pick largest face
                target_face = max(faces_bboxes, key=lambda b: b[2] * b[3])
                (x, y, w, h) = target_face
                
                H, W, _ = frame.shape
                x = max(0, x)
                y = max(0, y)
                w = min(w, W - x)
                h = min(h, H - y)
                
                face_crop = frame[y:y+h, x:x+w]
                if face_crop.size > 0:
                    recog_thread.input_queue.put(face_crop)

            # 3. Draw UI
            if not config.HEADLESS:
                # Draw all detected faces
                for (x, y, w, h) in faces_bboxes:
                    name = recog_thread.current_user_name
                    
                    # 🧠 THE 5-SECOND MEMORY
                    # If the camera sees a real person, remember their name and the time!
                    if name != "Unknown" and name != "Scanning...":
                        recent_face_name = name
                        recent_face_time = time.time()

                    color = (0, 255, 0) if name != "Unknown" and name != "Scanning..." else (0, 0, 255)
                    if name == "Scanning...": color = (255, 255, 0)

                    cv2.rectangle(frame, (x, y), (x+w, y+h), color, 2)
                    cv2.putText(frame, name, (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

                # Global Status
                if not door_lock.is_locked:
                     remaining = int(unlock_expiry_time - time.time()) if unlock_expiry_time else 0
                     cv2.putText(frame, f"ACCESS GRANTED ({remaining}s)", (50, frame.shape[0] - 50), 
                            cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 3)

                # FPS
                fps = 1.0 / (time.time() - start_det + 1e-6)
                cv2.putText(frame, f"FPS: {fps:.1f}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
                
                cv2.imshow('Face Recognition System', frame)

                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
            else:
                # Headless: small delay to prevent CPU spin
                door_lock.set_unknown() # Set to unknown state when not showing video
                time.sleep(0.01)

            # ----------------------------------------
            # 💳2. THE NON-BLOCKING RFID CHECK
            # ----------------------------------------
            card_id = rfid_reader.read_id_no_block()
        
            if card_id:
                print(f"\n💳 Card Swiped! ID: {card_id}")
                
                # Step A: Is this card in our database?
                if card_id in USER_DATABASE:
                    expected_name = USER_DATABASE[card_id]
                    print(f"✅ Valid Card. This card belongs to: {expected_name}")
                    
                    # Step B: Did the camera see this EXACT person recently?
                    time_since_seen = time.time() - recent_face_time
                    
                    if recent_face_name == expected_name and time_since_seen <= MEMORY_WINDOW:
                        print(f"🔓 2FA SUCCESS! Face ({recent_face_name}) matches Card. Opening door...")
                        
                        door_lock.unlock() # Trigger the physical lock
                        recent_face_name = None # Wipe the memory so they can't reuse the swipe!
                        
                    else:
                        print(f"❌ 2FA FAILED! The camera doesn't see {expected_name} right now.")
                        
                else:
                    print("❌ Unknown Card! Access Denied.")


    except KeyboardInterrupt:
        print("\nKeyboard interrupt received.")
    finally:
        print("🧹 Turning off Camera and GPIO pins...")
        recog_thread.stop()
        cap.release()
        if not config.HEADLESS:
            cv2.destroyAllWindows() #closes camera window forcefully
        logger.close()
        door_lock.cleanup()
        GPIO.cleanup()
        rfid_reader.release()


if __name__ == "__main__":
    main()
