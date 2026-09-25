# Phase 3A: Raspberry Pi robot agent

**Agent:** sol · **Runs:** Phase 3, when the physical robot is ready, in parallel with 3B
**Status:** outline. Refine with the user before starting (open questions below).

## Goal
The real robot joins the loop exactly like the virtual one: it connects to
`/ws/robot`, streams its camera, obeys `cmd`s, stops on its own watchdog,
and reports its pose so the digital twin (3B) can follow it.

## Stack
Python 3 on the Pi, `websockets` client, `picamera2` (or OpenCV for a USB
camera), the motor driver library for whatever controller the robot uses,
systemd for autostart.

## Build (outline)
1. Start from `hub/sim/robot_sim.py` and swap its two hardware functions:
   - `get_frame()` → picamera2 capture, JPEG 640x480, quality ~70, 20 fps;
   - `drive(vx, vy)` → omni-wheel inverse kinematics → motor controller.
2. Watchdog exactly as protocol.md: no `cmd` within `ttl_ms` → motors off.
   Motors also off on disconnect and at start.
3. Pose for the twin: dead-reckoning `x`, `y` (heading fixed while there's no
   rotation) from wheel encoders if the robot has them, otherwise from the
   commands actually applied. Telemetry at 10 Hz with `x`, `y`, `heading`,
   `battery_v`.
4. Config file or CLI for the hub URL; reconnect forever with backoff;
   systemd unit so it starts on boot.
5. Record the camera's mounting height and pitch and hand them to 3B.

## Open questions (ask the user first)
- Motor controller and wiring: which board/library? How many omni wheels (3 or 4) and at what angles?
- Wheel encoders or IMU on board?
- Camera: Pi Camera module (which) or USB?
- Max safe speed indoors?

## Acceptance
- [ ] Drives from the BCI and the dashboard override exactly like the virtual robot, with the same axis signs
- [ ] Watchdog stops it within `ttl_ms` when the WiFi drops or the hub dies
- [ ] Video on the phone at ~20 fps; pose telemetry at 10 Hz
- [ ] Starts on boot

## Handoff notes
_(fill in when done)_
