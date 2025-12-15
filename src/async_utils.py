import threading
import queue
import time
import cv2

class FaceRecognitionThread(threading.Thread):
    def __init__(self, recognizer, door_lock, logger):
        super().__init__()
        self.recognizer = recognizer
        self.door_lock = door_lock
        self.logger = logger
        
        # IO
        self.input_queue = queue.Queue(maxsize=1)
        self.running = True
        self.daemon = True # Ensure thread dies with main program
        
        # Shared State
        self.current_user_name = "Scanning..."
        self.current_distance = 1.0
        self.last_recognition_time = 0
        
        self.cooldown = 2.0 # Seconds to sleep after processing

    def run(self):
        print("[THREAD] FaceRecognitionThread started.")
        while self.running:
            try:
                # Wait for a frame (blocking, but with timeout to check self.running)
                try:
                    frame_crop = self.input_queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                
                # Check cooldown (redundant if main loop controls input, but good for safety)
                # Actually, main loop checks queue full. 
                
                # Process
                start_proc = time.time()
                name, distance = self.recognizer.verify(frame_crop)
                
                self.current_user_name = name
                self.current_distance = distance
                
                # Logic
                if name != "Unknown":
                    print(f"[THREAD] Match: {name} ({distance:.2f})")
                    self.door_lock.unlock()
                    
                    # Log
                    self.logger.log_event(name, "access_granted", 1.0 - distance)
                    
                    # Manage lock timer in Thread or rely on Main?
                    # The prompt says "If matching found, call door_lock.unlock() ... Sleep for 2.0 seconds".
                    # Main.py previous logic had a 5s timer.
                    # The prompt for THIS task says "Sleep for 2.0 seconds after a check".
                    # It implies the thread just hits unlock, and sleeps. 
                    # Does the door re-lock?
                    # The previous Main.py `unlock_expiry` logic was nice. 
                    # If I move unlock to here, I need to ensure the door eventually locks.
                    # Thread logic: call unlock.
                    # DoorLock logic: it stays unlocked until lock() is called.
                    # Who calls lock()? 
                    # If I follow the prompt STRICTLY: "Refactor main.py... If match found, call unlock()... Sleep".
                    # It doesn't explicitly say "Remove auto-lock". 
                    # I should probably keep the auto-lock logic in Main or add it here.
                    # Main loop is better suited for "Time-based events" like auto-locking 
                    # because the thread is sleeping for 2s.
                    # I will keep the thread doing `unlock()`.
                    
                    # Sleep to prevent overheating
                    time.sleep(self.cooldown)
                    
                else:
                    # Unknown
                    # Just sleep a bit less? Or simplified:
                    time.sleep(0.5) # Short sleep if unknown
                
            except Exception as e:
                print(f"[THREAD] Error: {e}")

    def stop(self):
        self.running = False
