import time
from gpiozero import AngularServo

# Servo 1 on GPIO 12 (Pin 32), Servo 2 on GPIO 13 (Pin 33)
# Pulse widths 0.5ms to 2.4ms match SG90 standard 180-degree sweep (-90 to +90)
servo1 = AngularServo(12, min_angle=-90, max_angle=90, min_pulse_width=0.0005, max_pulse_width=0.0024)
servo2 = AngularServo(13, min_angle=-90, max_angle=90, min_pulse_width=0.0005, max_pulse_width=0.0024)

try:
    print("Initializing Servos to Center (0 deg)...")
    servo1.angle = 0
    servo2.angle = 0
    time.sleep(1.0)

    # --- SERVO 1 SEQUENCE ---
    print("\n--- Testing Servo 1 ---")
    print("Turning CCW 30 degrees (to -30 deg)...")
    servo1.angle = -30
    time.sleep(1.0)

    print("Turning CW 60 degrees (to +30 deg)...")
    servo1.angle = 30
    time.sleep(1.0)

    print("Turning CCW 30 degrees (back to 0 deg)...")
    servo1.angle = 0
    time.sleep(1.0)
    servo1.detach()  # Stop PWM pulses to eliminate idle buzzing

    # --- SERVO 2 SEQUENCE ---
    print("\n--- Testing Servo 2 ---")
    print("Turning CCW 30 degrees (to -30 deg)...")
    servo2.angle = -30
    time.sleep(1.0)

    print("Turning CW 60 degrees (to +30 deg)...")
    servo2.angle = 30
    time.sleep(1.0)

    print("Turning CCW 30 degrees (back to 0 deg)...")
    servo2.angle = 0
    time.sleep(1.0)
    servo2.detach()

    print("\nServo test completed successfully.")

except KeyboardInterrupt:
    print("\nAborting servo test...")
finally:
    servo1.detach()
    servo2.detach()
    print("Servo signals detached.")
