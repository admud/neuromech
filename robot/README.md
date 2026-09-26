# robot: the rover side

The rover is a 4-wheel mecanum chassis with a Raspberry Pi, a dual
L298N-style motor driver, and a pan/tilt camera gimbal on two servos. The
Pi runs [`pi/motor_udp.py`](pi/motor_udp.py), a UDP listener on **port
5005**, reachable as `NeuroMech.local` on the same network (e.g. the iPhone
hotspot).

## `pi/`: code that runs on the Raspberry Pi

This is the team member's code, copied in unchanged. It needs `gpiozero`
on the Pi.
- **`motor_udp.py`**: the rover controller. Run on the Pi:
  `python3 motor_udp.py`.
  - **Movement words:**
    - `FWD`, `BACK`;
    - `LEFT`/`RIGHT`, which **strafe**;
    - `TURN_L`/`TURN_R`, which pivot on the spot;
    - `STOP`.
    Speed is fixed: the motors are on/off, no PWM.
  - **Camera gimbal words:** `CAM_LEFT`/`CAM_RIGHT`/`CAM_UP`/`CAM_DOWN`
    move it 15° per word; `CAM_CENTER` recentres it.
  - **Commands don't queue.** Each packet sets the motors at once, and
    `STOP` brakes at once.
  - **Watchdog:** if no packet arrives for **0.6 s** while moving, it
    brakes. So a direction keeps driving only while its word keeps
    arriving. The bridge resends every 0.2 s.
  - **Wiring (BCM GPIO), as (forward, backward) pins:**
    - FL 17/27, FR 22/23, RL 24/25, RR 5/6;
    - servos: pan 12, tilt 13 (hardware PWM).
  - **Mixing** matches the hub's `mecanumWheelSpeeds`: strafe left is
    FL−, FR+, RL+, RR−.
- **`test_dc_motors.py`**: a scripted motor check: forward, back, then
  strafe left and right. **Lift the chassis first.**
- **`test_servos.py`**: sweeps each gimbal servo ±30° and back to centre.

## `ugv_controller.py`: manual keyboard control

The team's test tool, driving the rover by hand with no headset:
```
control\.venv\Scripts\python robot\ugv_controller.py
```
- **Keys:** w/s = forward/back, a/d = left/right, space or x = STOP,
  q = quit.
- **Each key needs Enter,** because the tool reads a line at a time.
  Each word drives for about 0.6 s, until the Pi's watchdog brakes.
- **Address:** it sends to `NeuroMech.local`. Edit `TARGET_IP` if that
  name doesn't resolve.

## Driving the rover from the BCI

Use the bridge, [`hub/ugv/`](../hub/ugv/README.md). It turns the hub's
commands into these same UDP words.
- It resends the current direction every 0.2 s, well inside the Pi's
  0.6 s watchdog.
- On any stop it sends `STOP` three times.
- It sends `STOP` on its own if the hub goes quiet.
```
control\.venv\Scripts\python -m hub --window 2
control\.venv\Scripts\python -m hub.ugv --video none      # --host <Pi IP> if NeuroMech.local fails
control\.venv\Scripts\python -m hub.gui
```
Don't run `ugv_controller.py` and the bridge at the same time: both would
be commanding the rover.
