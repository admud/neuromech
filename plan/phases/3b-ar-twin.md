# Phase 3B: AR digital twin on the real camera feed

**Agent:** opus2 (the twin's owner) · **Runs:** Phase 3, when the real robot camera works, in parallel with 3A
**Status:** outline. Refine with the user before starting (open questions below).

## Goal
The demo happens on flat, empty ground, so we bring the virtual arena
into the real world. The twin (1E) follows the real robot's pose, and the
virtual walls, obstacles and gates are drawn **onto the real camera feed**
in the right perspective, as if they were really on the floor. The virtual
walls also stop the real robot. The digital world and the physical robot
become one system: a digital twin.

## Stack
three.js (same scene as 1E), OpenCV in Python for camera calibration and
optional ArUco marker localisation, the existing hub protocol plus small
additions.

## Approach (outline)

1. **Camera model.** Calibrate the Pi camera's intrinsics once with a
   printed checkerboard (`hub/tools/calibrate_camera.py`, OpenCV). Measure
   the mount height and pitch (3A). Because the ground is flat and the
   camera is rigidly mounted, the floor plane is known in camera coordinates
   without SLAM.

2. **Robot pose.**
   - Baseline: the robot's own odometry from telemetry (3A).
   - Drift fix: a few ArUco markers taped to the floor at known positions,
     detected in the video frames (`cv2.aruco`, runs on the hub). Each
     detection gives an absolute pose to snap to.
   - "Re-zero here" button on the dashboard.

3. **AR rendering.** A twin mode `?mode=ar`:
   - the live robot frame as the background;
   - the three.js camera set from the calibrated intrinsics and the robot's
     pose;
   - only the walls/obstacles/gates layer (1E keeps it separable) drawn on
     top, with shadows on the floor for grounding.

4. **Getting AR to the operator's phone.** Decide at the start of the phase:
   - **A.** The twin page composites frames and publishes them to the hub
     as the phone's video. Needs a small protocol addition (a video-publish
     socket, and the hub choosing which stream the phone gets). The phone
     page stays unchanged. Adds one encode (~20–40 ms).
   - **B.** The phone renders the overlay itself from pose + world. Lowest
     latency, but puts three.js next to the 120 Hz flicker on the phone,
     which risks frame drops.
   - Recommendation: A, keeping the phone's flicker untouched.

5. **Virtual-wall geofence.** The hub loads the same world file. With the
   robot's pose, the arbiter zeroes any velocity component that would drive
   into a virtual wall. It shows on the twin as a collision.

## Open questions (ask the user first)
- Size of the demo floor area? The virtual arena should match it.
- OK to tape ArUco markers on the floor?
- AR on the phone, on the laptop, or both?
- Should virtual walls physically stop the real robot (geofence), or only be visual?

## Acceptance
- [ ] Virtual walls stay put on the real floor while the robot drives (visually stable within a few cm over a lap)
- [ ] The twin's third-person view tracks the real robot
- [ ] Geofence stops the real robot at virtual walls (if chosen)
- [ ] Phone still hits its fps target with AR on

## Handoff notes
_(fill in when done)_
