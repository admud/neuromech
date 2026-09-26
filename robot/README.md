# robot: the rover side

The rover is a 4-wheel mecanum chassis with a Raspberry Pi and a dual
L298N-style motor driver. The Pi runs a UDP listener on **port 5005**,
reachable as `NeuroMech.local` on the same network (e.g. the iPhone
hotspot).
- **Commands:** plain-text words, `FWD`, `BACK`, `LEFT`, `RIGHT` and
  `STOP`. LEFT/RIGHT strafe.
- **Each command moves the rover for 1 second,** at a fixed speed.

The Pi's own code isn't in this repo yet.

## `ugv_controller.py`: manual keyboard control

The team's test tool, driving the rover by hand with no headset:
```
control\.venv\Scripts\python robot\ugv_controller.py
```
- **Keys:** w/s = forward/back, a/d = left/right, space or x = STOP,
  q = quit.
- **Each key needs Enter,** because the tool reads a line at a time.
- **Address:** it sends to `NeuroMech.local`. Edit `TARGET_IP` if that
  name doesn't resolve.

## Driving the rover from the BCI

Use the bridge, [`hub/ugv/`](../hub/ugv/README.md). It turns the hub's
commands into these same UDP words.
- It resends while you keep a direction.
- On any stop it sends `STOP` three times.
- It sends `STOP` on its own if the hub goes quiet.
```
control\.venv\Scripts\python -m hub --window 2
control\.venv\Scripts\python -m hub.ugv --video none      # --host <Pi IP> if NeuroMech.local fails
control\.venv\Scripts\python -m hub.gui
```
Don't run `ugv_controller.py` and the bridge at the same time: both would
be commanding the rover.
