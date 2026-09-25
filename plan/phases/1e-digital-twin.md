# Phase 1E: 3D digital twin and virtual robot

**Agent:** opus2 · **Runs:** Phase 1, in parallel with 1A–1D, 1F

## Goal
A 3D simulation of the robot in a virtual arena, running in the browser.
Two jobs:

1. **Virtual robot, for building and testing now.** The twin page connects
   to the hub as the robot. It receives `cmd`s, moves the robot through the
   virtual arena (walls, obstacles, checkpoint gates), and streams the
   robot's **first-person camera** back as the video feed. The operator's
   iPhone then shows that virtual camera view, so the full BCI loop works
   with the headset and no physical robot.
2. **The cool screen for the demo.** The laptop shows a third-person view of
   the arena and robot, with the brain-control state visualised. It's
   embedded in the dashboard (1D) and also runs full screen on its own.

Later (Phase 3) the same scene becomes a **digital twin** of the real robot:
it follows the real robot's pose, and its virtual walls are overlaid on the
real camera feed as AR. Build with that in mind (see *Designed for Phase 3*).

## Read first
- [../protocol.md](../protocol.md): `/ws/robot` (you are a robot),
  `/ws/dashboard` (you read `state`), world file, robot watchdog rule
- [../architecture.md](../architecture.md): digital twin section
- [../README.md](../README.md#rules-for-every-agent): git rules

## You own
`web/twin/` (e.g. `index.html`, `twin.js`, `world.js`, `physics.js`,
`fpv.js`, `hud.js`, `style.css`, `worlds/default.json`, `vendor/three/`),
**except** `web/twin/robot_model.js` and `web/twin/model.html`, which belong
to 1F (astra).

## Stack
three.js (WebGL), vendored locally. Plain ES modules, **no build step and no
CDN** (the venue may be offline).
- Get it with npm into a temp dir outside the repo
  (`npm pack three@0.186.1`, or `npm install three@0.186.1 --prefix <tmp>`).
  Copy into `web/twin/vendor/three/`: `build/three.module.js` **and**
  `build/three.core.js` (the module imports it), any addons you use from
  `examples/jsm/` (e.g. `controls/OrbitControls.js`), and three's `LICENSE`.
- Addons import the bare specifier `"three"`, so add an import map in
  `index.html`: `{"imports": {"three": "./vendor/three/three.module.js"}}`.

## Build

1. **Modes** (URL params)
   - `?mode=robot` (default): **be the virtual robot**.
     - Connect to `/ws/robot` and send `hello` with `name: "virtual"`.
     - Apply each `cmd`. Enforce the watchdog: no `cmd` within `ttl_ms` →
       stop, `watchdog_stopped: true`.
     - Stream the FPV camera as JPEG at ~20 fps.
     - Send `telemetry` at 10 Hz with pose (`x`, `y`, `heading`, `collision`).
     - Reply `pong` to `ping`.
   - `?mode=view`: **spectator**. Render the robot at the pose in
     `state.robot.telemetry`, smoothly interpolated. Used when something else
     is the robot (another twin tab, the Python sim, later the real RPi).
   - Both modes also connect to `/ws/dashboard` **read-only** (never send)
     to get `state` for the HUD.
   - `&embed=1`: compact layout for the dashboard iframe.

2. **World** from `worlds/default.json` (schema in protocol.md): arena
   floor with grid, walls and obstacles (boxes), checkpoint gates, spawn
   pose, robot geometry and camera. Default: a ~6 x 4 m arena, a few walls
   making a simple course, 3 gates.

3. **Robot**: the robot is a **4-wheel mecanum** robot. Its 3D model comes
   from 1F: `createRobotModel({camera: world.robot.camera})` in
   `robot_model.js` (contract in [1f-robot-model.md](1f-robot-model.md)).
   - Until 1F lands, use a placeholder box with four cylinders behind the
     same interface.
   - Each frame, call `model.update(dt, mecanumWheelSpeeds(vx, vy, 0, model.dims))`
     so the wheels spin the way real mecanum wheels would.
   - Collision radius = `model.dims.footprintRadius`.
   - No rotation this phase: heading stays at the spawn heading.
   - **Motion:** in the robot frame, `vx` forward and `vy` left, times
     `robot.max_speed_mps` from the world file. Integrate from
     `performance.now()` deltas so a dropped frame doesn't change the speed.
   - **Collisions:** the robot is a circle, walls/obstacles are boxes. Stop
     at walls and slide along them; set `collision: true` in telemetry while
     touching.

4. **FPV camera = the video feed**: a perspective camera at
   `model.cameraMount`, with pitch, horizontal FOV and 640x480 from
   `world.robot.camera`. Render it
   offscreen at ~20 fps and encode to JPEG (quality ~0.7, `toBlob` /
   `convertToBlob`). Send each frame as one binary message on `/ws/robot`.
   Never queue: if the previous encode or send is still in flight, skip the
   frame.

5. **Main view**, which needs to look good on a projector:
   - Cameras: third-person chase (default), orbit (OrbitControls) and
     top-down; `C` cycles between them.
   - Shadows, decent lighting, a trail behind the robot.
   - Gates light up when driven through, plus a lap timer.

6. **Brain-control HUD** from `state`:
   - ARMED/DISARMED as a coloured ring under the robot.
   - The decoded direction as a glowing arrow on the robot, filling with
     `dwell` progress.
   - The four decoder score bars.
   - Link status and the measured phone fps.
   - Readable in `embed` mode too.

7. **Keys in embed mode**: while the iframe has focus, the dashboard never
   sees key presses, and Esc/Space are its STOP keys. Forward every
   `keydown`/`keyup` for Esc, Space, arrows, WASD, 1–4 and 0 to the parent
   with `window.parent.postMessage({type: "twin-key", event: "keydown"|"keyup", key}, "*")`.
   Keep `C` (camera cycle) for yourself.

8. **Hidden tabs**: browsers throttle hidden tabs, so FPV and physics pause
   when the twin tab isn't visible. Show a clear warning in the page, and
   document "keep the twin visible" in your handoff notes.

## Designed for Phase 3 (don't build it, don't block it)
- World units in metres. Frame: x forward, y left, **z up**; `heading` is
  yaw, counter-clockwise from +x. three.js is y-up by default, so set
  `THREE.Object3D.DEFAULT_UP.set(0, 0, 1)` before creating anything. The
  robot model is built z-up too.
- Keep the camera model explicit: intrinsics come from FOV + resolution, and
  the mount from height + pitch, so it can later be swapped for a
  calibrated real camera.
- Keep walls/obstacles/gates on their own layer that can be rendered alone
  on a transparent background. That's the AR overlay later.
- Pose comes in through one function (`setPose(x, y, heading)`) whether it's
  from local physics or from telemetry.

## Acceptance
- [ ] Standalone `/twin/` as the robot: dashboard override and sim gaze drive it through the arena; walls stop it; gates and timer work
- [ ] The phone page (or `/ws/video` viewer) shows the FPV feed at ~20 fps with no build-up of lag
- [ ] Watchdog stops the virtual robot when `cmd`s stop
- [ ] `?mode=view` follows a robot driven by another client
- [ ] `&embed=1` works inside an iframe
- [ ] 60 fps main view on this laptop while streaming FPV
- [ ] Works with no internet (three.js vendored, no CDN)
- [ ] Handoff notes filled in, committed, @main tagged

## Handoff notes
_(fill in when done)_
