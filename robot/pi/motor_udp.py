import socket
import sys
import time
from gpiozero import DigitalOutputDevice, AngularServo

# --- MOTOR GPIO CONFIGURATION ---
# Format: (Forward Pin, Backward Pin)
FL = (DigitalOutputDevice(17), DigitalOutputDevice(27))
FR = (DigitalOutputDevice(22), DigitalOutputDevice(23))
RL = (DigitalOutputDevice(24), DigitalOutputDevice(25))
RR = (DigitalOutputDevice(5),  DigitalOutputDevice(6))

# --- SERVO GPIO CONFIGURATION (Hardware PWM pins) ---
# Pan: GPIO 12 (Pin 32) | Tilt: GPIO 13 (Pin 33)
pan_servo = AngularServo(12, min_angle=-90, max_angle=90, min_pulse_width=0.0005, max_pulse_width=0.0024)
tilt_servo = AngularServo(13, min_angle=-90, max_angle=90, min_pulse_width=0.0005, max_pulse_width=0.0024)

# Keep track of servo positions
current_pan = 0
current_tilt = 0

def set_motor(motor, state):
    # state: 1 = forward, -1 = reverse, 0 = brake
    if state == 1:
        motor[0].on(); motor[1].off()
    elif state == -1:
        motor[0].off(); motor[1].on()
    else:
        motor[0].off(); motor[1].off()

def brake():
    set_motor(FL, 0); set_motor(FR, 0)
    set_motor(RL, 0); set_motor(RR, 0)

def set_chassis(fl, fr, rl, rr):
    set_motor(FL, fl); set_motor(FR, fr)
    set_motor(RL, rl); set_motor(RR, rr)

def handle_servo(command):
    global current_pan, current_tilt
    step = 15
    if command == "CAM_LEFT":
        current_pan = min(90, current_pan + step)
        pan_servo.angle = current_pan
    elif command == "CAM_RIGHT":
        current_pan = max(-90, current_pan - step)
        pan_servo.angle = current_pan
    elif command == "CAM_UP":
        current_tilt = min(90, current_tilt + step)
        tilt_servo.angle = current_tilt
    elif command == "CAM_DOWN":
        current_tilt = max(-90, current_tilt - step)
        tilt_servo.angle = current_tilt
    elif command == "CAM_CENTER":
        current_pan, current_tilt = 0, 0
        pan_servo.angle = 0
        tilt_servo.angle = 0

def execute_command(cmd):
    cmd = cmd.strip().upper()

    # Movement Commands
    if cmd == "FWD":
        set_chassis(1, 1, 1, 1)
    elif cmd == "BACK":
        set_chassis(-1, -1, -1, -1)
    elif cmd == "LEFT":          # Lateral strafe left
        set_chassis(-1, 1, 1, -1)
    elif cmd == "RIGHT":         # Lateral strafe right
        set_chassis(1, -1, -1, 1)
    elif cmd == "TURN_L":        # In-place counter-clockwise pivot
        set_chassis(-1, 1, -1, 1)
    elif cmd == "TURN_R":        # In-place clockwise pivot
        set_chassis(1, -1, 1, -1)
    elif cmd == "STOP":
        brake()
    
    # Camera Gimbal Commands
    elif cmd.startswith("CAM_"):
        handle_servo(cmd)

# --- NETWORK CONFIGURATION ---
UDP_IP = "0.0.0.0"
UDP_PORT = 5005

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((UDP_IP, UDP_PORT))
sock.settimeout(0.6)  # Safety Watchdog threshold in seconds

print("=" * 45)
print(f"UGV Tactical Controller Active on UDP Port {UDP_PORT}")
print("Watchdog failsafe engaged (0.6s heartbeat timeout)")
print("=" * 45)

# Center camera servos at startup
pan_servo.angle = 0
tilt_servo.angle = 0
time.sleep(0.3)
pan_servo.detach()
tilt_servo.detach()

is_moving = False

try:
    while True:
        try:
            data, addr = sock.recvfrom(1024)
            cmd = data.decode("utf-8").strip()
            print(f"[{addr[0]}] -> {cmd}")
            execute_command(cmd)
            is_moving = (cmd not in ["STOP", ""] and not cmd.startswith("CAM_"))
        except socket.timeout:
            # If no packet received within 0.6s while wheels are moving, cut motor power
            if is_moving:
                brake()
                is_moving = False

except KeyboardInterrupt:
    print("\nShutting down controller...")
finally:
    brake()
    pan_servo.detach()
    tilt_servo.detach()
    sock.close()
    print("All outputs safely neutralized.")
