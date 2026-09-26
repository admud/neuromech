# hub/ugv: rover bridge

`python -m hub.ugv` connects to the hub as the robot and turns its commands
into the rover's UDP words on port 5005:
- forward → `FWD`, back → `BACK`, left → `LEFT`, right → `RIGHT`, zero → `STOP`;
- **new direction:** sent at once, then repeated every 0.5 s while it's held;
- **stopping:** `STOP` is sent three times.

Drive the real rover (laptop and Pi on the same network):
```
control\.venv\Scripts\python -m hub --window 2
control\.venv\Scripts\python -m hub.ugv --video none        # --host <Pi IP> if NeuroMech.local doesn't resolve
control\.venv\Scripts\python -m hub.gui
```
First run: wheels off the ground, and drive with the arrow keys in the
display. Then hold ↑ for 5 s, release, and time how long the wheels keep
turning. About 0 s is right; more than 1 s means the Pi queues commands,
so restart the bridge with `--repeat 1.0`.

## Details (handoff notes)

Run from the repository root with the Python 3.10 venv:

```powershell
control/.venv/Scripts/python.exe -m hub --device sim
control/.venv/Scripts/python.exe -m hub.ugv --host <Pi-IP>
```

The bridge defaults to `NeuroMech.local:5005`, resolves that name once at
startup, and prints the selected IPv4 address. `--hub` changes the hub robot
socket, `--port` changes the UDP port, `--repeat` changes the motion repeat
period (default 0.5 s), and `--video none` disables the test JPEG feed.
`--dry-run` prints the UDP words instead of sending them.

The bridge speaks `/ws/robot` as `ugv`, including `pong`, telemetry at about
5 Hz, and a 640×480 test JPEG at about 10 Hz by default. It sends a new UDP
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

Physical behavior remains to be checked by the user: if the Pi queues each
one-second motion command rather than restarting its timer, repeated commands
could delay STOP on the Pi. The bridge cannot clear that remote queue. Use
the brief's forward-then-STOP timing check before driving on the floor.
