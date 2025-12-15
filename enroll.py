import cv2
import os
import pickle
import sys
from src.detector import FaceDetector
from src.recognizer import FaceIdentifier

def enroll_user():
    name = input("Enter the name of the new user: ").strip()
    if not name:
        print("Name cannot be empty.")
        return

    print("Initializing system... (First run may take time to download models)")
    
    # Initialize our modular components
    # This ensures consistency with main.py logic
    try:
        detector = FaceDetector()
        recognizer = FaceIdentifier()
        # Force model load/download now so it doesn't hang later
        print("Loading FaceNet512 model...")
        _ = recognizer.get_embedding(face_image=None, warmup=True) 
        # Note: We need a slight tweak to recognizer to support warmup or just call build_model directly here.
        # Ideally, we just let the first usage resolve it, but we warn the user.
        # Actually, let's just instantiate them. The hang is likely the model downloading.
    except Exception as e:
        print(f"Error initializing modules: {e}")
        return

    cap = cv2.VideoCapture(0)
    
    print(f"\nPosition your face in the camera.")
    print(f"Wait for the GREEN BOX to appear.")
    print(f"Ensure the video window is selected/focused.")
    print(f"Press 's' to capture and save '{name}'.")
    print(f"Press 'q' to quit.\n")

    while True:
        ret, frame = cap.read()
        if not ret:
            print("Failed to grab frame")
            break

        # detection
        faces = detector.detect(frame)
        
        # Draw feedback
        status_color = (0, 0, 255) # Red by default
        status_text = "No Face"
        
        target_face_crop = None
        
        if faces:
            # Assume the largest face is the target
            # faces is list of (x, y, w, h)
            # detect already filters small faces
            target_face = max(faces, key=lambda b: b[2] * b[3])
            (x, y, w, h) = target_face
            
            # Draw box
            cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 255, 0), 2)
            
            # Prepare crop for saving
            # Add a safe crop logic
            H, W, _ = frame.shape
            x = max(0, x) 
            y = max(0, y)
            w = min(w, W - x)
            h = min(h, H - y)
            
            target_face_crop = frame[y:y+h, x:x+w]
            status_color = (0, 255, 0)
            status_text = "Ready (Press 's')"

        # UI Text
        cv2.putText(frame, status_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, status_color, 2)
        cv2.imshow('Enrollment', frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('s'):
            if target_face_crop is not None and target_face_crop.size > 0:
                print("Capturing... Processing embedding...")
                
                # Show "Processing" on screen - force update
                cv2.putText(frame, "Processing...", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 0, 0), 2)
                cv2.imshow('Enrollment', frame)
                cv2.waitKey(1)
                
                try:
                    # Use the recognizer helper or direct DeepFace
                    # We reuse the recognizer class logic for consistency
                    embedding = recognizer.get_embedding(target_face_crop)
                    
                    if embedding:
                        save_path = os.path.join("db", "authorized_users", f"{name}.pkl")
                        with open(save_path, "wb") as f:
                            pickle.dump(embedding, f)
                        
                        print(f"Successfully saved user '{name}' to {save_path}")
                        print("Exiting...")
                        break
                    else:
                        print("Failed to generate embedding. Try again.")
                except Exception as e:
                    print(f"Error during enrollment: {e}")
            else:
                print("No face detected! Please wait for the green box.")

        elif key == ord('q'):
            print("Enrollment cancelled.")
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    if not os.path.exists("db/authorized_users"):
        os.makedirs("db/authorized_users")
    enroll_user()
