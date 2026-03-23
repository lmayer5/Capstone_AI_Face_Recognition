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
        self.pin_relay = config.GPIO_RELAY        # Electric Door Strike Relay
        self.pin_reed = config.GPIO_REED_SWITCH   # Reed Switch
        self.pin_pir = config.GPIO_PIR            # PIR Motion Sensor

        # Try to initialize GPIO on Pi
        try:
            import RPi.GPIO as GPIO
            self.GPIO = GPIO
            self.is_pi = True

            self.GPIO.setmode(self.GPIO.BCM)
            self.GPIO.setwarnings(False)

            # Set up LED and Relay pins as outputs
            self.GPIO.setup(self.pin_green, self.GPIO.OUT)
            self.GPIO.setup(self.pin_yellow, self.GPIO.OUT)
            self.GPIO.setup(self.pin_red, self.GPIO.OUT)
            self.GPIO.setup(self.pin_relay, self.GPIO.OUT)

            # Set up Reed Switch as input with Pull-Up resistor
            self.GPIO.setup(self.pin_reed, self.GPIO.IN, pull_up_down=self.GPIO.PUD_UP)
            
            # Set up PIR motion sensor as input
            self.GPIO.setup(self.pin_pir, self.GPIO.IN)

            # Start in locked state: red ON, others OFF, relay OFF
            self._set_locked_leds()
            self.GPIO.output(self.pin_relay, self.GPIO.LOW)
            print(f"[HARDWARE] Raspberry Pi GPIO initialized.")
            print(f"  Green LED    → GPIO {self.pin_green}")
            print(f"  Yellow LED   → GPIO {self.pin_yellow}")
            print(f"  Red LED      → GPIO {self.pin_red}")
            print(f"  Relay        → GPIO {self.pin_relay}")
            print(f"  Reed Switch  → GPIO {self.pin_reed}")
            print(f"  PIR Sensor   → GPIO {self.pin_pir}")

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
            print(">> [HARDWARE] LEDs: UNKNOWN (Red)")
            
    def is_door_open(self):
        """Returns True if the physical door is open, detected via Reed switch.
        Assumes Reed Switch is normally closed (connected to GND) when door is shut (LOW).
        When the door opens, the magnet moves away, switch opens, pulled HIGH by Internal Resistor."""
        if self.is_pi:
            return self.GPIO.input(self.pin_reed) == self.GPIO.HIGH
        return False # Mock open state    
        
    def is_motion_detected(self):
        """Returns True if PIR sensor detects motion."""
        if self.is_pi:
            return self.GPIO.input(self.pin_pir) == self.GPIO.HIGH
        return False # Mock no motion

    # --- Lock Control ---

    def unlock(self):
        if not self.is_locked:
            return  # Already unlocked

        self.is_locked = False
        self._set_unlocked_leds()
        if self.is_pi:
            self.GPIO.output(self.pin_relay, self.GPIO.HIGH) # Activate relay
        else:
            print(">> [HARDWARE] DOOR UNLOCKED — LEDs: GREEN, RELAY: ON")

    def lock(self):
        if self.is_locked:
            return  # Already locked

        self.is_locked = True
        self._set_locked_leds()
        if self.is_pi:
            self.GPIO.output(self.pin_relay, self.GPIO.LOW) # Deactivate relay
        else:
            print(">> [HARDWARE] DOOR LOCKED — LEDs: RED, RELAY: OFF")

    def cleanup(self):
        """Turn off all LEDs and release GPIO."""
        if self.is_pi:
            self.GPIO.output(self.pin_green, self.GPIO.LOW)
            self.GPIO.output(self.pin_yellow, self.GPIO.LOW)
            self.GPIO.output(self.pin_red, self.GPIO.LOW)
            self.GPIO.output(self.pin_relay, self.GPIO.LOW)
            self.GPIO.cleanup()
            print("[HARDWARE] GPIO cleaned up.")
