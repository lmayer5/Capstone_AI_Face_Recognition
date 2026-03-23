"""
Hardware controller for the door lock and status LEDs.
On Raspberry Pi: drives GPIO pins for LEDs (green/yellow/red).
On other platforms: prints mock output to terminal.
"""
import platform
import time
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import config


class DoorLock:
    def __init__(self):
        self.is_locked = True
        self.is_pi = False

        self.pin_green = config.GPIO_GREEN_LED    # Access Granted
        self.pin_yellow = config.GPIO_YELLOW_LED  # Scanning / Processing
        self.pin_red = config.GPIO_RED_LED        # Locked / Unknown

        # Try to initialize GPIO on Pi
        try:
            import RPi.GPIO as GPIO
            self.GPIO = GPIO
            self.is_pi = True

            self.GPIO.setmode(self.GPIO.BCM)
            self.GPIO.setwarnings(False)

            # Set up LED pins as outputs
            self.GPIO.setup(self.pin_green, self.GPIO.OUT)
            self.GPIO.setup(self.pin_yellow, self.GPIO.OUT)
            self.GPIO.setup(self.pin_red, self.GPIO.OUT)

            # Start in locked state: red ON, others OFF
            self._set_locked_leds()
            print(f"[HARDWARE] Raspberry Pi GPIO initialized.")
            print(f"  Green LED  → GPIO {self.pin_green}")
            print(f"  Yellow LED → GPIO {self.pin_yellow}")
            print(f"  Red LED    → GPIO {self.pin_red}")

        except ImportError:
            self.is_pi = False
            print("[HARDWARE] RPi.GPIO not found. Running in MOCK mode (Windows/Other).")
        except Exception as e:
            self.is_pi = False
            print(f"[HARDWARE] Error initializing GPIO: {e}. Running in MOCK mode.")

    # --- LED Control ---

    def _set_locked_leds(self):
        """Red ON, Green OFF, Yellow OFF"""
        if self.is_pi:
            self.GPIO.output(self.pin_red, self.GPIO.HIGH)
            self.GPIO.output(self.pin_green, self.GPIO.LOW)
            self.GPIO.output(self.pin_yellow, self.GPIO.LOW)

    def _set_unlocked_leds(self):
        """Green ON, Red OFF, Yellow OFF"""
        if self.is_pi:
            self.GPIO.output(self.pin_green, self.GPIO.HIGH)
            self.GPIO.output(self.pin_red, self.GPIO.LOW)
            self.GPIO.output(self.pin_yellow, self.GPIO.LOW)

    def set_scanning(self):
        """Yellow ON, Red OFF, Green OFF — indicates active face processing."""
        if self.is_pi:
            self.GPIO.output(self.pin_yellow, self.GPIO.HIGH)
            self.GPIO.output(self.pin_red, self.GPIO.LOW)
            self.GPIO.output(self.pin_green, self.GPIO.LOW)
        else:
            print(">> [HARDWARE] LEDs: SCANNING (Yellow)")

   def set_unknown(self):
        """Yellow Off, Red ON, Green OFF — indicates Unknown face."""
        if self.is_pi:
            self.GPIO.output(self.pin_yellow, self.GPIO.LOW)
            self.GPIO.output(self.pin_red, self.GPIO.HIGH)
            self.GPIO.output(self.pin_green, self.GPIO.LOW)
        else:
            print(">> [HARDWARE] LEDs: SCANNING (Yellow)")    

    # --- Lock Control ---

    def unlock(self):
        if not self.is_locked:
            return  # Already unlocked

        self.is_locked = False
        self._set_unlocked_leds()
        if not self.is_pi:
            print(">> [HARDWARE] DOOR UNLOCKED — LEDs: GREEN")

    def lock(self):
        if self.is_locked:
            return  # Already locked

        self.is_locked = True
        self._set_locked_leds()
        if not self.is_pi:
            print(">> [HARDWARE] DOOR LOCKED — LEDs: RED")

    def cleanup(self):
        """Turn off all LEDs and release GPIO."""
        if self.is_pi:
            self.GPIO.output(self.pin_green, self.GPIO.LOW)
            self.GPIO.output(self.pin_yellow, self.GPIO.LOW)
            self.GPIO.output(self.pin_red, self.GPIO.LOW)
            self.GPIO.cleanup()
            print("[HARDWARE] GPIO cleaned up.")
