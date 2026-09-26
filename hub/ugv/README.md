# hub/ugv: rover bridge

`python -m hub.ugv` connects to the hub as the robot and turns its commands
into the rover's UDP words on port 5005:
- forward → `FWD`, back → `BACK`, left → `LEFT`, right → `RIGHT`, zero → `STOP`;
- **new direction:** sent at once, then repeated every **0.2 s** while it's held;
- **stopping:** `STOP` is sent three times.

Drive the real rover (laptop and Pi on the same network):
```
control\.venv\Scripts\python -m hub --window 2
control\.venv\Scripts\python -m hub.ugv --video none        # --host <Pi IP> if NeuroMech.local doesn't resolve
control\.venv\Scripts\python -m hub.gui
```
**The Pi side is [`robot/pi/motor_udp.py`](../../robot/pi/motor_udp.py).**
- It **doesn't queue**: each packet sets the motors at once, and `STOP`
  brakes at once.
- It brakes by itself after **0.6 s** without a packet.
- That's why the bridge repeats every 0.2 s: one late or lost packet
  can't make the rover stutter.

First run: wheels off the ground, and drive with the arrow keys in the
display.

## Video and the motion freeze

`--video` picks what the bridge sends to the hub as the robot's video:
- `test`: a test pattern (default);
- `none`: no video;
- **the rover's camera:**
  - a stream URL, e.g. `http://NeuroMech.local:8000/stream.mjpg` or
    `rtsp://...`;
  - or a device number, e.g. `1` for a USB video receiver plugged into the
    laptop.

  The bridge reads it in a thread and keeps only the newest frame. If the
  stream dies or goes quiet for 2 s, it reopens it every second.

**The freeze:** the motors and the camera share one battery, so the camera
browns out while the rover drives ("Signal Lost", or a stalled stream).
- From the moment the bridge sends a movement word, it stops passing the
  camera's frames on.
- Instead it re-sends the last frame from before the rover moved, twice a
  second.
- Live frames resume **1 s after `STOP`**, time for the camera to recover.
  Change it with `--freeze-settle <s>`.
- `--no-freeze` turns the freeze off.
- The telemetry carries `video_frozen`, and the display shows **FROZEN**
  in the bottom-left margin.
- It applies to the test pattern too, so `--dry-run --video test` shows it
  without a rover.

Tested (2026-09-26) against a fake rover on localhost. Its camera served
"SIGNAL LOST" frames while the motors ran and for 0.5 s after:
- the display saw only the frozen pre-drive frame while driving, and none
  of the 59 "SIGNAL LOST" frames;
- live video came back 1 s after the stop;
- `hub/tests/test_ugv_camera.py` covers the gate, a stalling MJPEG
  stream, and the bridge end to end.

## Details (handoff notes)

Run from the repository root with the Python 3.10 venv:

```powershell
control/.venv/Scripts/python.exe -m hub --device sim
control/.venv/Scripts/python.exe -m hub.ugv --host <Pi-IP>
```

The bridge defaults to `NeuroMech.local:5005`, resolves that name once at
startup, and prints the selected IPv4 address. `--hub` changes the hub robot
socket, `--port` changes the UDP port, `--repeat` changes the motion repeat
period (default 0.2 s; it was 0.5 s before the Pi's 0.6 s watchdog was known), and `--video none` disables the test JPEG feed.
`--dry-run` prints the UDP words instead of sending them. `--freeze-settle`
and `--no-freeze` control the video freeze (above).

The bridge speaks `/ws/robot` as `ugv`, including `pong`, telemetry at about
5 Hz, and a 640×480 test JPEG at about 10 Hz by default (or the camera's
frames, at the camera's rate, scaled to 640 wide). It sends a new UDP
direction immediately, then repeats only that direction at the chosen
interval. A change to zero and a 500 ms hub command timeout send three STOPs
about 20 ms apart. STOP then repeats about once a second. Link loss,
replacement, Ctrl+C, and other exits also send a final three STOPs. Motion
commands are never queued in the bridge.

After a command timeout, the bridge closes its robot socket and reconnects.
Buffered movement commands from the old socket are ignored. On the new
socket, motion remains locked until the hub sends a zero command; a stray
moving command cannot restart the rover after watchdog STOP. Closing the
old socket also gives the hub a robot-loss signal so it can disarm.

The copied `robot/ugv_controller.py` matches the user's Downloads file
byte for byte (SHA-256 `7774707709cc0dc1619e97c0782d9cb3bf53b00fd60f4b870eec50eb5c57b85b`).

Verification: `control/.venv/Scripts/python.exe -m pytest
hub/tests/test_ugv_bridge.py -q` passes 7 tests against localhost fake UDP
and WebSocket servers. A live `hub --device sim` session on port 55547 sent
`FWD` after simulated up gaze and `STOP` on disarm into a localhost UDP
recorder. No packet was sent to the real rover.
The other 71 hub tests also passed during the initial handoff.

**Resolved (2026-09-26):** the Pi code (`robot/pi/motor_udp.py`) applies each packet immediately, so it doesn't queue, and brakes after 0.6 s without a packet. The default repeat is now 0.2 s. Tested against an emulation of that listener: 6 s of driving with packets every 0.20 s, no watchdog brakes, and `STOP` on release.
