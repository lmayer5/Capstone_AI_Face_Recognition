import platform
import time

class DoorLock:
    def __init__(self, pin=17):
        self.pin = pin
        self.is_locked = True
        self.is_pi = False
        
        # Check platform or ability to import RPi.GPIO
        try:
            import RPi.GPIO as GPIO
            self.GPIO = GPIO
            self.is_pi = True
            
            self.GPIO.setmode(self.GPIO.BCM)
            self.GPIO.setup(self.pin, self.GPIO.OUT)
            self.lock() # Ensure startup state is locked
            print(f"[HARDWARE] Running on Raspberry Pi. GPIO {self.pin} initialized.")
            
        except ImportError:
            self.is_pi = False
            print("[HARDWARE] RPi.GPIO not found. Running in MOCK mode (Windows/Other).")
        except Exception as e:
            self.is_pi = False
            print(f"[HARDWARE] Error initializing GPIO: {e}. Running in MOCK mode.")

    def unlock(self):
        if not self.is_locked:
            return  # Already unlocked
            
        self.is_locked = False
        if self.is_pi:
            self.GPIO.output(self.pin, self.GPIO.HIGH)
        else:
            print(">> [HARDWARE] SOLENOID UNLOCKED (GPIO HIGH)")

    def lock(self):
        if self.is_locked:
            return # Already locked
            
        self.is_locked = True
        if self.is_pi:
            self.GPIO.output(self.pin, self.GPIO.LOW)
        else:
            print(">> [HARDWARE] SOLENOID LOCKED (GPIO LOW)")

    def cleanup(self):
        if self.is_pi:
            self.GPIO.cleanup()
