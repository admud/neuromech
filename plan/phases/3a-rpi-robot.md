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

## Known hardware (from [../assets/robot-photo-1.jpg](../assets/robot-photo-1.jpg))
- **Raspberry Pi Zero** (W or 2 W?), two-deck aluminium chassis, 4 mecanum
  wheels with DC motors.
- Red **dual L298N-style driver board** (4 motor channels): direction pins
  + PWM enable per motor, driven from Pi GPIO (`gpiozero` / `RPi.GPIO`,
  software or hardware PWM).
- LM2596 buck converter; AA battery packs.
- No camera fitted yet.

## Build notes
- Motor mixing: `mecanumWheelSpeeds` from `web/twin/robot_model.js` (1F),
  ported to Python and scaled to PWM duty.
- **Check the wheels are fitted in the same handedness the formula
  assumes** (strafe left → FL/RR backward, FR/RL forward). If not, swap
  signs in the mixing, not in the protocol.
- Pi Zero is slow. Use picamera2's hardware MJPEG encoder, not OpenCV
  encoding, and drop to 15 fps / 480p if needed.

## Open questions (ask the user first)
- Pi Zero W or Zero 2 W?
- GPIO pin mapping from the Pi to the driver board (IN1–IN4, ENA/ENB per chip)?
- Wheel encoders or an IMU? (Probably not, so pose would come from the commands.)
- Which camera module, and where will it be mounted (height, tilt)?
- Max safe speed indoors?

## Acceptance
- [ ] Drives from the BCI and the dashboard override exactly like the virtual robot, with the same axis signs
- [ ] Watchdog stops it within `ttl_ms` when the WiFi drops or the hub dies
- [ ] Video on the phone at ~20 fps; pose telemetry at 10 Hz
- [ ] Starts on boot

## Handoff notes
_(fill in when done)_
