import time
from gpiozero import DigitalOutputDevice

# Pin Mapping: (Forward Pin, Backward Pin)
FL = (DigitalOutputDevice(17), DigitalOutputDevice(27))
FR = (DigitalOutputDevice(22), DigitalOutputDevice(23))
RL = (DigitalOutputDevice(24), DigitalOutputDevice(25))
RR = (DigitalOutputDevice(5),  DigitalOutputDevice(6))

def set_motor(motor, state):
    # state: 1 = forward, -1 = reverse, 0 = brake/coast
    if state == 1:
        motor[0].on()
        motor[1].off()
    elif state == -1:
        motor[0].off()
        motor[1].on()
    else:
        motor[0].off()
        motor[1].off()

def brake():
    set_motor(FL, 0)
    set_motor(FR, 0)
    set_motor(RL, 0)
    set_motor(RR, 0)

def move(fl, fr, rl, rr, duration, label=""):
    print(f"Executing: {label} ({duration}s)")
    set_motor(FL, fl)
    set_motor(FR, fr)
    set_motor(RL, rl)
    set_motor(RR, rr)
    time.sleep(duration)
    brake()
    time.sleep(0.5)  # Buffer pause to prevent inrush spike on reversal

try:
    print("Elevate chassis or place in an open area. Starting in 2 seconds...")
    time.sleep(2)

    # 1. Forward 1 second
    move(1, 1, 1, 1, 1.0, "FORWARD")

    # 2. Backward 2 seconds
    move(-1, -1, -1, -1, 2.0, "BACKWARD")

    # 3. Forward 1 second
    move(1, 1, 1, 1, 1.0, "FORWARD")

    # 4. Strafe Left 1 second (FL-, FR+, RL+, RR-)
    move(-1, 1, 1, -1, 1.0, "STRAFE LEFT")

    # 5. Strafe Right 2 seconds (FL+, FR-, RL-, RR+)
    move(1, -1, -1, 1, 2.0, "STRAFE RIGHT")

    # 6. Strafe Left 1 second (FL-, FR+, RL+, RR-)
    move(-1, 1, 1, -1, 1.0, "STRAFE LEFT")

    print("Mecanum sequence finished successfully.")

except KeyboardInterrupt:
    print("\nAborting sequence...")
finally:
    brake()
    print("Motors safely stopped.")
