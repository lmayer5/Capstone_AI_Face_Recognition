import cv2
import time
from src.detector import FaceDetector
from src.recognizer import FaceIdentifier
from src.database import EventLogger
from src.hardware import DoorLock
from src.async_utils import FaceRecognitionThread

def main():
    # Initialize components
    detector = FaceDetector()
    recognizer = FaceIdentifier()
    logger = EventLogger()
    door_lock = DoorLock()
    
    # Initialize and start Background Thread
    recog_thread = FaceRecognitionThread(recognizer, door_lock, logger)
    recog_thread.start()
    
    cap = cv2.VideoCapture(0)
    
    # Lock Logic State
    unlock_expiry_time = None 
    
    print("Starting Main Loop (Threaded)...")
    print("Press 'q' to quit.")

    try:
        while True:
            # 0. Check Auto-Lock Logic
            # Detect if door was unlocked by thread
            if not door_lock.is_locked:
                # If we haven't set a timer yet, set it now
                if unlock_expiry_time is None:
                    unlock_expiry_time = time.time() + 5.0
                    print("[SYSTEM] Door Unlocked. Timer started.")
                
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
                break
            
            # 1. Detection (Main Thread - Fast)
            start_det = time.time()
            faces_bboxes = detector.detect(frame)
            
            # 2. Delegate to Recognition Thread
            # Only send if thread is ready (queue not full) and we have a face
            if faces_bboxes and not recog_thread.input_queue.full():
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
            # Draw all detected faces
            for (x, y, w, h) in faces_bboxes:
                # Use current status from thread
                # Note: This status applies to the last processed face, not necessarily THIS specific box
                # But for a single-person scenario or MVP, it's acceptable.
                
                name = recog_thread.current_user_name
                color = (0, 255, 0) if name != "Unknown" and name != "Scanning..." else (0, 0, 255)
                if name == "Scanning...": color = (255, 255, 0)

                cv2.rectangle(frame, (x, y), (x+w, y+h), color, 2)
                cv2.putText(frame, name, (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

            # Global Status
            if not door_lock.is_locked:
                 # Access Granted UI
                 remaining = int(unlock_expiry_time - time.time()) if unlock_expiry_time else 0
                 cv2.putText(frame, f"ACCESS GRANTED ({remaining}s)", (50, frame.shape[0] - 50), 
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 3)

            # FPS
            fps = 1.0 / (time.time() - start_det + 1e-6)
            cv2.putText(frame, f"FPS: {fps:.1f}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
            
            cv2.imshow('Face Recognition System', frame)

            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

    except KeyboardInterrupt:
        pass
    finally:
        print("Stopping...")
        recog_thread.stop()
        cap.release()
        cv2.destroyAllWindows()
        logger.close()
        door_lock.cleanup()


if __name__ == "__main__":
    main()
