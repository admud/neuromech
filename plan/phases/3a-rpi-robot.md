# Phase 3A: Raspberry Pi robot agent

**Agent:** sol · **Runs:** Phase 3, when the physical robot is ready
**Status:** outline. Refine with the user before starting (open questions below).

## Goal
The real robot takes the virtual robot's place in the loop: it connects to
`/ws/robot`, streams its camera, obeys `cmd`s, and stops on its own watchdog.

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
3. Telemetry at 2–10 Hz: applied `vx`/`vy`, `watchdog_stopped`, `battery_v` if measurable.
4. Config file or CLI for the hub URL; reconnect forever with backoff;
   systemd unit so it starts on boot.

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
- Which camera module, and where will it be mounted (height, tilt)?
- Max safe speed indoors?

## Acceptance
- [ ] Drives from the BCI and the dashboard override exactly like the virtual robot, with the same axis signs
- [ ] Watchdog stops it within `ttl_ms` when the WiFi drops or the hub dies
- [ ] Video on the phone at ~20 fps
- [ ] Starts on boot

## Handoff notes
_(fill in when done)_
