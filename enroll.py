import cv2
import os
import pickle
import sys
from src.detector import FaceDetector
from src.recognizer import FaceIdentifier
from src.camera import get_camera
import config

def enroll_user():
    name = input("Enter the name of the new user: ").strip()
    if not name:
        print("Name cannot be empty.")
        return

    print("Initializing system... (First run may take time to download models)")
    
    # Initialize our modular components
    try:
        detector = FaceDetector()
        recognizer = FaceIdentifier()
        # Force model load/download now
        print("Loading FaceNet512 model...")
        _ = recognizer.get_embedding(face_image=None, warmup=True) 
    except Exception as e:
        print(f"Error initializing modules: {e}")
        return

    # Use platform-aware camera
    cap = get_camera()
    
    print(f"\nPosition your face in the camera.")
    print(f"Wait for the GREEN BOX to appear.")
    if not config.HEADLESS:
        print(f"Ensure the video window is selected/focused.")
        print(f"Press 's' to capture and save '{name}'.")
        print(f"Press 'q' to quit.\n")
    else:
        print(f"Press Enter in the terminal to capture when ready.")
        print(f"Press Ctrl+C to quit.\n")

    while True:
        ret, frame = cap.read()
        if not ret:
            print("Failed to grab frame")
            break

        # Detection
        faces = detector.detect(frame)
        
        # Draw feedback
        status_color = (0, 0, 255)  # Red by default
        status_text = "No Face"
        
        target_face_crop = None
        
        if faces:
            target_face = max(faces, key=lambda b: b[2] * b[3])
            (x, y, w, h) = target_face
            
            # Draw box
            if not config.HEADLESS:
                cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 255, 0), 2)
            
            # Prepare crop for saving
            H, W, _ = frame.shape
            x = max(0, x) 
            y = max(0, y)
            w = min(w, W - x)
            h = min(h, H - y)
            
            target_face_crop = frame[y:y+h, x:x+w]
            status_color = (0, 255, 0)
            status_text = "Ready (Press 's')" if not config.HEADLESS else "Face detected — press Enter in terminal"

        # Show UI if display is available
        if not config.HEADLESS:
            cv2.putText(frame, status_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, status_color, 2)
            cv2.imshow('Enrollment', frame)

            key = cv2.waitKey(1) & 0xFF
            if key == ord('s'):
                if target_face_crop is not None and target_face_crop.size > 0:
                    _save_enrollment(recognizer, target_face_crop, name, frame)
                    break
                else:
                    print("No face detected! Please wait for the green box.")

            elif key == ord('q'):
                print("Enrollment cancelled.")
                break
        else:
            # Headless: print status to terminal
            if faces:
                print(f"\r[ENROLL] {status_text}", end="", flush=True)
            else:
                print(f"\r[ENROLL] No face detected...", end="", flush=True)
            
            # Non-blocking check for Enter key isn't easy cross-platform.
            # Just use a small delay; user will Ctrl+C and use GUI mode for enrollment.
            import time
            time.sleep(0.1)

    cap.release()
    if not config.HEADLESS:
        cv2.destroyAllWindows()


def _save_enrollment(recognizer, face_crop, name, frame):
    """Process and save the face embedding."""
    print("\nCapturing... Processing embedding...")

    if not config.HEADLESS:
        cv2.putText(frame, "Processing...", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 0, 0), 2)
        cv2.imshow('Enrollment', frame)
        cv2.waitKey(1)
    
    try:
        embedding = recognizer.get_embedding(face_crop)
        
        if embedding:
            save_path = os.path.join(config.DB_PATH, f"{name}.pkl")
            with open(save_path, "wb") as f:
                pickle.dump(embedding, f)
            
            print(f"Successfully saved user '{name}' to {save_path}")
        else:
            print("Failed to generate embedding. Try again.")
    except Exception as e:
        print(f"Error during enrollment: {e}")


if __name__ == "__main__":
    if not os.path.exists(config.DB_PATH):
        os.makedirs(config.DB_PATH)
    enroll_user()
