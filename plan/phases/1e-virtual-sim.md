# Phase 1E: 3D virtual sim (virtual robot)

**Agent:** opus2 · **Runs:** Phase 1, in parallel with 1A–1D, 1F

## Goal
A 3D simulation of our robot in a virtual arena, running in the laptop
browser. It exists so we can **test the whole BCI loop before the physical
robot is ready**:
- The sim page connects to the hub **as the robot**. It receives `cmd`s,
  drives the virtual robot around the arena (walls, obstacles, collisions),
  and streams the robot's **first-person camera** back as the video feed.
- The operator's iPhone shows that virtual camera view, exactly where the
  real camera feed will go later. Nothing upstream changes when the real
  robot replaces it.
- The laptop shows a third-person 3D view with the brain-control state, so
  testers can see what's happening. It's embedded in the dashboard (1D).

Once the real robot exists, the sim is no longer used in the loop. There's
no AR or digital-twin tracking of the real robot.

## Read first
- [../protocol.md](../protocol.md): `/ws/robot` (you are a robot),
  `/ws/dashboard` (you read `state`), world file, robot watchdog rule, iframe key forwarding
- [1f-robot-model.md](1f-robot-model.md): the robot model contract you consume
- [../README.md](../README.md#rules-for-every-agent): git rules

## You own
`web/twin/` (e.g. `index.html`, `twin.js`, `world.js`, `physics.js`,
`fpv.js`, `hud.js`, `style.css`, `worlds/default.json`, `vendor/three/`),
**except** `web/twin/robot_model.js` and `web/twin/model.html` (1F, astra).

## Stack
three.js (WebGL), vendored locally. Plain ES modules, **no build step and no
CDN** (the venue may be offline).
- Get it with npm into a temp dir outside the repo
  (`npm pack three@0.186.1`, or `npm install three@0.186.1 --prefix <tmp>`).
  Copy into `web/twin/vendor/three/`: `build/three.module.js` **and**
  `build/three.core.js` (the module imports it), any addons you use from
  `examples/jsm/` (e.g. `controls/OrbitControls.js`), and three's `LICENSE`.
  Do this first: 1F's preview page uses the same copy.
- Addons import the bare specifier `"three"`, so add an import map in
  `index.html`: `{"imports": {"three": "./vendor/three/three.module.js"}}`.
- **Z-up world:** x forward, y left, z up, metres. Set
  `THREE.Object3D.DEFAULT_UP.set(0, 0, 1)` before creating anything. The
  robot model is built z-up too.

## Build

1. **Be the robot**
   - Connect to `/ws/robot` and send `hello` with `name: "virtual"`.
   - Apply each `cmd`. Enforce the watchdog: no `cmd` within `ttl_ms` →
     stop, `watchdog_stopped: true`.
   - Send `telemetry` at 10 Hz (`vx`, `vy`, `watchdog_stopped`, `x`, `y`,
     `heading`, `collision`). Reply `pong` to `ping`.
   - Also connect to `/ws/dashboard` **read-only** (never send) to get
     `state` for the HUD.
   - `?embed=1`: compact layout for the dashboard iframe.

2. **World** from `worlds/default.json` (schema in protocol.md): a ~6 x 4 m
   arena with a floor grid and a few walls/obstacles (boxes) forming a
   simple course to practise driving, plus the spawn pose.

3. **Robot**: our **4-wheel mecanum** robot from 1F:
   `createRobotModel({camera: world.robot.camera})` (contract in
   [1f-robot-model.md](1f-robot-model.md)).
   - Until 1F lands, use a placeholder box with four cylinders behind the
     same interface.
   - **Motion:** in the robot frame, `vx` forward and `vy` left, times
     `robot.max_speed_mps`. Integrate from `performance.now()` deltas so a
     dropped frame doesn't change the speed.
   - Each frame call `model.update(dt, mecanumWheelSpeeds(vx, vy, 0, model.dims))`,
     so the wheels spin like real mecanum wheels.
   - No rotation this phase: heading stays at the spawn heading.
   - **Collisions:** the robot is a circle of radius
     `model.dims.footprintRadius`; walls/obstacles are boxes. Stop at walls
     and slide along them, with `collision: true` in telemetry while touching.

4. **FPV camera = the video feed**: a perspective camera at
   `model.cameraMount`, with pitch, horizontal FOV and 640x480 from
   `world.robot.camera`. Render it offscreen at ~20 fps and encode to JPEG
   (quality ~0.7, `toBlob` / `convertToBlob`). Send each frame as one binary
   message on `/ws/robot`. Never queue: if the previous encode or send is
   still in flight, skip the frame.

5. **Main view**
   - Cameras: third-person chase (default), top-down and orbit
     (OrbitControls); `C` cycles between them.
   - Shadows, clean lighting, a trail behind the robot.

6. **Brain-control HUD** from `state`:
   - ARMED/DISARMED as a coloured ring under the robot.
   - The decoded direction as an arrow on the robot, filling with `dwell`
     progress.
   - The four decoder score bars.
   - Link status and the measured phone fps.
   - Readable in `embed` mode too.

7. **Keys in embed mode**: while the iframe has focus, the dashboard never
   sees key presses, and Esc/Space are its STOP keys. Forward every
   `keydown`/`keyup` for Esc, Space, arrows, WASD, 1–4 and 0 to the parent
   with `window.parent.postMessage({type: "twin-key", event: "keydown"|"keyup", key}, "*")`.
   Keep `C` (camera cycle) for yourself.

8. **Hidden tabs**: browsers throttle hidden tabs, so FPV and physics pause
   when the sim isn't visible. Show a clear warning in the page, and
   document "keep the sim visible" in your handoff notes.

## Acceptance
- [ ] `/twin/` as the robot: dashboard override and sim gaze drive it through the arena; walls stop it
- [ ] The phone page (or any `/ws/video` viewer) shows the FPV feed at ~20 fps with no build-up of lag
- [ ] Wheels spin correctly for forward, back and both strafes
- [ ] Watchdog stops the virtual robot when `cmd`s stop
- [ ] `?embed=1` works inside an iframe, including key forwarding
- [ ] 60 fps main view on this laptop while streaming FPV
- [ ] Works with no internet (three.js vendored, no CDN)
- [ ] Handoff notes filled in, committed, @main tagged

## Handoff notes
_(fill in when done)_
