import socket

# Target the Pi by its hostname or local IP
TARGET_IP = "NeuroMech.local"  # Replace with the Pi's raw IP (e.g. 192.168.X.X) if hostname fails
TARGET_PORT = 5005

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

print("--- TACTICAL UGV MANUAL OVERRIDE ---")
print("Controls: w (FWD), s (BACK), a (LEFT), d (RIGHT), space/x (STOP), q (QUIT)")

COMMAND_MAP = {
    'w': "FWD",
    's': "BACK",
    'a': "LEFT",
    'd': "RIGHT",
    ' ': "STOP",
    'x': "STOP"
}

try:
    while True:
        key = input("Enter command: ").strip().lower()
        if key == 'q':
            sock.sendto(b"STOP", (TARGET_IP, TARGET_PORT))
            break
        if key in COMMAND_MAP:
            cmd = COMMAND_MAP[key]
            sock.sendto(cmd.encode("utf-8"), (TARGET_IP, TARGET_PORT))
            print(f"Sent: {cmd}")
        else:
            print("Invalid key. Use w, a, s, d, or space.")
except KeyboardInterrupt:
    sock.sendto(b"STOP", (TARGET_IP, TARGET_PORT))