import evdev

print("🔍 Scanning for USB Input Devices...\n")

# Get a list of all devices plugged into the Pi
devices = [evdev.InputDevice(path) for path in evdev.list_devices()]

for device in devices:
    print(f"📍 Address: {device.path}")
    print(f"🏷️  Name: {device.name}")
    print("-" * 30)