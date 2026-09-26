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
- [x] `/twin/` as the robot: dashboard override and sim gaze drive it through the arena; walls stop it
  (override tested against `python -m hub --stub`; sim gaze not yet, it needs 1B's `--device sim`, but it arrives as the same `cmd`)
- [x] The phone page (or any `/ws/video` viewer) shows the FPV feed at ~20 fps with no build-up of lag
- [x] Wheels spin correctly for forward, back and both strafes (the sim passes `mecanumWheelSpeeds(vx*max, vy*max, 0, dims)` in m/s; the per-wheel look is 1F's model)
- [x] Watchdog stops the virtual robot when `cmd`s stop
- [x] `?embed=1` works inside an iframe, including key forwarding
- [x] 60 fps main view on this laptop while streaming FPV (~117 fps measured)
- [x] Works with no internet (three.js vendored, no CDN)
- [x] Handoff notes filled in, committed, @main tagged

## Handoff notes

**What exists** (`web/twin/`)
- `index.html` (import map, HUD markup) · `twin.js` (main: scene, robot, cameras, loop, keys) ·
  `net.js` (`RobotLink` on `/ws/robot` with the watchdog, read-only `DashLink` on `/ws/dashboard`) ·
  `physics.js` (circle vs oriented boxes, slides along walls) · `world.js` (arena from the world file) ·
  `fpv.js` (robot camera → JPEG → `/ws/robot`) · `fpv_worker.js` (JPEG encoder) · `hud.js` (3D ring/arrow + HTML overlay) ·
  `placeholder_robot.js` (used only if `robot_model.js` fails to import) · `style.css` · `worlds/default.json` ·
  `vendor/three/` (three r186: `three.module.js`, `three.core.js`, `addons/controls/OrbitControls.js`, LICENSE).

**Run**
- `control\.venv\Scripts\python -m hub --stub` (or `--device sim`), then open
  `http://localhost:8765/twin/` (or let the dashboard embed `/twin/?embed=1`). It connects as robot `virtual`.
- URL params: `embed=1` compact layout; `mode=view` watch only (doesn't take the robot slot);
  `cam=chase|top|orbit`; `world=<name>` loads `worlds/<name>.json`; `hub=host:port` other hub.
- Keys: `C` cycles chase → top → orbit. In an iframe, Esc, Space, arrows, WASD, 1–4, 0 go to the
  parent as `{type:"twin-key", event, key}` (keydown and keyup); `C` stays in the sim.
- Console/test hook: `window.twin` = `{pose, motion, robot, dash, fpv, setCamMode, model, world}`.

**Behaviour**
- `cmd` → velocity (`vx`,`vy` × `robot.max_speed_mps`, robot frame), integrated from `performance.now()`
  deltas (capped at 0.1 s). No `cmd` for `ttl_ms` (or socket down) → zero, `watchdog_stopped: true`.
- Telemetry at 10 Hz from a timer: `vx, vy, watchdog_stopped, battery_v:null, x, y, heading, collision`,
  plus optional `sim_hidden` (true while the tab is hidden, i.e. physics paused). Pong on ping.
- FPV: 640x480, hfov 70 → vfov computed, pitch from `cameraMount`, ≤ 20 fps, JPEG q0.7 (~10–12 kB).
  Pipeline (after @main found only 4–5 fps under load): render into a 4x MSAA render target on the
  **main** renderer (one GL context), async PBO readback (`readRenderTargetPixelsAsync`), then
  `fpv_worker.js` flips rows, applies the sRGB curve (render targets are linear) and encodes on a
  CPU-only `OffscreenCanvas` (`willReadFrequently`; a GPU-backed one queued behind the 3D view).
  Up to 3 frames in flight (readback is latency-bound, ~100–150 ms under load). A due slot that finds
  the pipeline or socket busy goes out on the next free rAF. Never queues: a frame that finishes older
  than one already sent, or finds `ws.bufferedAmount > 0`, is dropped. The PiP shows the encoded frames.
- Main view capped at 60 fps (spare GPU goes to the FPV); shadows PCF 1024.
- After updating `web/twin/` files, hard-reload (Ctrl+F5): Chrome may serve cached modules.
- HUD marks (ring, dwell arrow) and the trail are on layer 1, which the FPV camera doesn't render,
  so none of it reaches the phone's video.
- Ring: green armed, red disarmed, grey no hub state. Arrow on the floor in the command direction:
  full green (bci) / blue (override); amber filling with `dwell.count/needed` before it activates.
- Robot turns red while touching a wall (`setHighlight`).
- Two sim tabs in one browser: the newest takes `/ws/robot`, older ones release it (BroadcastChannel)
  and show "Take over as robot". Across browsers, a sim closed right after connecting 3 times in a row
  (or with close code 4001 / reason "replaced") stops reconnecting instead of fighting.

**World file (additive optional fields)**
- The perimeter is implicit from `arena.size`; `arena.wall_h`/`wall_t` set its height/thickness (0.3/0.1).
- `walls[].color`, and `goal: {x, y, r}` (green pad + flag at the far end of the course).
- `default.json`: 6x4 m, spawn (-2.5, 0), a two-wall slalom (forward, strafe right round the blue wall,
  forward, strafe left round the orange one, forward to the goal) plus three boxes.

**Keep the sim visible.** Browsers throttle hidden tabs: physics and FPV stop (the phone's video freezes),
telemetry drops to ~1 Hz with `sim_hidden: true`, and the page shows a red "Sim hidden" banner.
Don't minimise the dashboard window or switch its tab during a run.

**Tested** (headless Chrome with the laptop's Intel GPU)
- Mock hub: hello/telemetry/pong, JPEG frames 19.9 fps; forward stops at exactly x = wall − radius
  with `collision: true`; fwd+right slides round the wall end; cmds stopped → still, `watchdog_stopped` in 0.5 s.
- Real hub `--stub`: arm + override left/up/none/right/down → moves +y/+x/stops/−y/−x; `/ws/video` viewer
  gets 20.0 fps valid JPEGs through the relay; disarm on `phone_lost` shown.
- Iframe: all forwarded keys arrive in the parent, `C` stays, others ignored. Second tab takes over cleanly.
- Main view ~117 fps while streaming. Placeholder model smoke-tested.
- FPV fix, retested with another agent's dashboard+phone set running on the same GPU: sim alone
  18–20 fps into the hub; dashboard (sim embedded) + phone page open: hub `video.in_fps` 11–19 (mostly 16–19).
  @main's `integration.mjs` (on other ports): 20/20 pass, `in_fps` 19, phone 17 frames/s.
  FPV JPEG checked by eye: upright, correct colours, matches the main view.
  (The headless phone page decodes fewer frames than the hub receives when the GPU is contended; the
  real iPhone decodes on its own hardware.)

**Not done / notes**
- Not yet seen on the iPhone itself, nor with 1B's `--device sim` sim gaze (both are Phase 2).
- Top view is a perspective camera from high above (slight parallax on walls), not orthographic.
- Suggestion for 1A (optional): close a replaced robot with code 4001 / reason "replaced" so the loser
  stops reconnecting at once instead of after 3 short connections.
