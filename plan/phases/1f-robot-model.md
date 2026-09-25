# Phase 1F: 3D model of the real robot

**Agent:** astra · **Runs:** Phase 1, in parallel with 1A–1E

## Goal
A three.js model of **our actual robot**, built in code from primitives:
no modelling software, no downloaded assets. The virtual sim (1E) uses it as
the virtual robot for testing before the physical robot is ready. It should
be recognisably *this* robot, and its wheels should turn the way real
mecanum wheels do.

This is a narrow, spatial-reasoning task with small input: one photo, the
contract below, and a handful of measurements. Keep your reading to that;
you don't need the rest of the codebase.

## Input
- Photo: [../assets/robot-photo-1.jpg](../assets/robot-photo-1.jpg)
- What's in it:
  - two-deck perforated **silver aluminium chassis** with rounded ends and
    slots, joined by **brass standoffs**;
  - **4 yellow mecanum wheels** with black rollers (~9 per wheel);
  - on the top deck:
    - a **red dual H-bridge driver board** (two L298N-style chips with
      black finned heatsinks, blue screw terminals, capacitors);
    - a **blue LM2596 buck converter** (with trim pot);
    - a **Raspberry Pi Zero** (green, 40-pin header) at one end;
    - a **2xAA battery holder**;
  - motors under the bottom deck, jumper wires on top.
- No camera is fitted yet. Add a small Pi-camera board on a bracket at the
  front, where `robot.camera` in the world file says (height, pitch).
- **Scale:** until the user sends measurements, use known parts as a
  ruler: Pi Zero board = 65 x 30 mm, AA cell = 50 x 14 mm. Keep every
  dimension in one `DIMS` object at the top of the file, so real
  measurements drop in without touching the geometry code.

## You own
`web/twin/robot_model.js`, `web/twin/model.html` (standalone preview page)

## Contract (1E codes against this; don't change it without @main)
```js
// web/twin/robot_model.js — three.js imported via the import map: import * as THREE from "three"
export function createRobotModel(opts = {}) -> {
  // opts.camera = world.robot.camera ({height_m, pitch_deg, ...}): place the camera prop there
  object,                    // THREE.Group. Metres, Z-UP, +x forward, +y left, origin on the ground under the chassis centre
  update(dt, wheelRadPerSec),// wheelRadPerSec = {fl, fr, rl, rr}; spins each wheel (rollers follow the hub)
  dims: { length, width, height, wheelRadius, wheelBase, trackWidth, footprintRadius },
  cameraMount: { position: [x, y, z], pitchDeg },   // where the FPV camera sits, robot frame
  setHighlight(color | null),// optional glow/outline used for ARMED / collision states
  dispose(),
}
export function mecanumWheelSpeeds(vx, vy, wz, dims) -> {fl, fr, rl, rr}
  // vx, vy in m/s (robot frame, vy left), wz in rad/s -> wheel speeds in rad/s.
  // k = (wheelBase + trackWidth) / 2, r = wheelRadius:
  //   fl = (vx - vy - k*wz) / r     fr = (vx + vy + k*wz) / r
  //   rl = (vx + vy - k*wz) / r     rr = (vx - vy + k*wz) / r
  // Also the reference for the Pi's motor mixing in Phase 3A.
```

## Build
1. **Chassis**
   - Both decks as `ExtrudeGeometry` from a 2D outline: rounded ends, and
     the slot/hole pattern as `Shape.holes`. Keep it to what reads from a
     metre away; you don't need every hole.
   - Brushed-metal material; brass standoffs.
2. **Mecanum wheels**
   - Yellow hub, plus rollers as instanced capsules around the rim with
     their axes at **45°** to the wheel axis.
   - Roller handedness must match `mecanumWheelSpeeds` (the mixer is
     fixed). The no-slip constraint is `(vx - r·ω, vy) · rollerAxis = 0`,
     so the **ground-contact roller axes** of FL and RR run along the x−y
     diagonal (forward-right) and those of FR and RL along x+y
     (forward-left). Seen from above, the top rollers then make an **X**.
     The behaviour in the acceptance list is the real test.
   - Wheels spin in `update()` from the given rad/s.
   - Motors: simple cylinders under the bottom deck.
3. **Electronics**
   - Driver board: red PCB, two heatsinks with fins, blue terminals, a few
     capacitors.
   - Buck converter, Pi Zero with header pins, 2xAA holder with cells.
   - Colours from the photo. Add a few wires as tubes if cheap.
4. **Camera**: small board + lens on a bracket at `cameraMount`.
5. **Performance**: shared geometries and materials, instancing for rollers
   and holes. Target well under 50 draw calls and under ~50k triangles.
   Casts and receives shadows.
6. **`model.html`**: standalone turntable preview (OrbitControls, a ground
   grid, axes helper) and a small panel with vx/vy sliders that drive
   `update()` through `mecanumWheelSpeeds`. That makes it easy to check the
   wheels turn the right way for forward, back and both strafes. It uses
   the vendored three.js from 1E (`./vendor/three/`). If that isn't there
   yet, vendor the same version (`three@0.186.1`) yourself exactly as the
   1E brief says, and tell @main.

## Acceptance
- [x] Recognisably the robot in the photo (chassis shape, yellow mecanum wheels, red driver board, Pi Zero)
- [x] Z-up, metres, +x forward, origin on the ground; `dims` and `cameraMount` accurate to the `DIMS` values
- [ ] In `model.html`: forward spins all wheels forward; strafe left spins FL/RR backward and FR/RL forward, with the rollers visibly angled consistently with that
- [x] Within the draw-call/triangle budget; no external assets
- [x] Handoff notes list every `DIMS` value and whether it was measured or estimated
- [x] Committed, @main tagged

## Handoff notes

Implemented in `web/twin/robot_model.js` and `web/twin/model.html`.
Initial working commit: `fa97fa7`; subsequent correction follows main's
approved handedness change in `e191140` / channel #200. The mixer is unchanged.

The model has two shared, extruded, genuinely perforated decks; brass
standoffs; four scalloped yellow wheels with nine instanced capsule rollers
each; motors; two red driver boards with heatsinks, terminals and capacitors;
blue buck converter; green Pi Zero with 40 pins; AA holder and two cells;
five wires; and a proposed camera mast. It needs no downloaded model,
texture, CDN, DOM, or network connection. Materials and geometries are shared
within each model; separate model instances own their resources independently.
`setHighlight(null)` clears the glow; `dispose()` is idempotent.

Run from the repo root:
```powershell
control/.venv/Scripts/python.exe -m http.server 8767 --bind 127.0.0.1 --directory web
# Open http://127.0.0.1:8767/twin/model.html
```
With the hub running, the same preview is `/twin/model.html`. It has no
WebSocket connection and cannot replace the virtual robot. The preview uses
1E's existing `vendor/three/three.module.js` and
`vendor/three/addons/controls/OrbitControls.js`; 1F did not alter vendor files.
Controls: vx/vy/wz sliders, four direction presets, Stop/Space/Escape,
turntable, top/reset views, and armed/collision highlights. Wheel speeds
are physical m/s and rad/s, so the sim must scale normalised commands first.

### Validation and remaining review

- **32 model draw calls and 15,648 triangles**, including electronics and
  wires. This is the model's colour pass; scene helpers and shadow passes add
  their own render work. Every model mesh casts and receives shadows.
- Actual vendored three.js imported in Node; checked all four direction
  signs, both yaw signs, zero velocity, animation, invalid dt/speed handling,
  custom camera placement/pitch, independent instances and one-time disposal.
- **108 no-slip constraints passed** across 27 combined vx/vy/wz commands,
  using the actual instanced roller-axis matrices and wheel locations.
  For each wheel, `(vx - wz*y - r*omega, vy + wz*x) dot rollerAxis = 0`.
- Verified the static geometry stays inside returned `dims` with camera
  heights 0.08, 0.12, 0.25 and 0.31 m. Preview module syntax and every local
  module HTTP import passed.
- Inspected a software rasterisation of the actual instantiated triangle
  geometry against the photo; the silhouette, materials and component layout
  are recognisable. This was a geometry check, not a WebGL screenshot.
- **Remaining:** live browser rendering and clicking the preview controls.
  CUA reported no connected browser. Automatic approval review rejected the
  headless Chrome test launch as "blocked by policy". The preview acceptance
  box above remains open for main's browser review; its underlying kinematics
  and geometry checks passed. No other implementation work is known pending.

Default returned dimensions (rounded): length **0.300 m**, width
**0.203678 m**, height **0.263485 m**, wheel radius **0.035 m**, wheelbase
**0.180 m**, track **0.174 m**, conservative footprint radius **0.181304 m**.
Length/width enclose the model symmetrically about its ground origin; wheel
bounds include the continuous rolling envelope. Height includes the camera.
`cameraMount = {position: [0.135, 0, 0.250], pitchDeg: -10}`; its position is
at the lens front, pointing +x with negative pitch down. Pass
`createRobotModel({camera: world.robot.camera})` to apply the world settings.

### Complete DIMS inventory

All lengths/positions below are **metres**; size arrays use local x/y/z
order. No physical robot dimensions have been measured. **Every value is a
photo estimate or proposed visual detail except** `pi.size` (the supplied
65 x 30 mm part reference), `battery.cellLength` and `battery.cellRadius`
(the supplied 50 x 14 mm reference), and the fixed design/count settings:
`wheel.rollerAngleDeg = 45`, `wheel.rollers = 9` (brief approximation),
`driver.fins = 6` (visual simplification), `pi.headerPitch = 0.00254`
(nominal connector pitch). Camera height/pitch defaults come from the
protocol world example; the entire camera/mast is proposed, not photographed.

| DIMS group | Every stored value |
|---|---|
| `chassis` | `length: 0.300`, `width: 0.150`, `cornerRadius: 0.035`, `thickness: 0.002`, `lowerZ: 0.050`, `upperZ: 0.098`, `slotLength: 0.026`, `slotWidth: 0.0035`, `holeRadius: 0.0018`, `standoffRadius: 0.003`, `boltRadius: 0.0028`, `boltHeight: 0.002` |
| `wheel` | `radius: 0.035`, `base: 0.180`, `track: 0.174`, `hubRadius: 0.026`, `hubWidth: 0.020`, `plateThickness: 0.002`, `coreRadius: 0.011`, `coreWidth: 0.027`, `rollerRadius: 0.006`, `rollerStraight: 0.025`, `rollers: 9`, `rollerAngleDeg: 45` |
| `motor` | `radius: 0.012`, `length: 0.033`, `gearbox: [0.032, 0.020, 0.023]` |
| `pcb` | `thickness: 0.0016`, `clearance: 0.004` |
| `driver` | `size: [0.043, 0.043]`, `centersX: [-0.025, 0.027]`, `y: 0`, `heatsink: [0.023, 0.018, 0.027]`, `finThickness: 0.0015`, `fins: 6`, `terminal: [0.012, 0.009, 0.010]`, `capRadius: 0.0033`, `capHeight: 0.012` |
| `buck` | `size: [0.043, 0.021]`, `center: [-0.074, 0.013]`, `inductorRadius: 0.005`, `inductorHeight: 0.005`, `trimmer: [0.007, 0.007, 0.009]` |
| `pi` | `size: [0.030, 0.065]`, `center: [-0.114, 0]`, `chip: [0.010, 0.012, 0.0015]`, `port: [0.007, 0.011, 0.004]`, `headerPitch: 0.00254`, `pinWidth: 0.00065`, `pinHeight: 0.006`, `headerBaseHeight: 0.0025` |
| `battery` | `size: [0.036, 0.058, 0.017]`, `center: [0.100, 0.005]`, `cellLength: 0.050`, `cellRadius: 0.007`, `wall: 0.002`, `terminalHeight: 0.001` |
| `camera` | `x: 0.135`, `height: 0.250`, `pitchDeg: -10`, `board: [0.0016, 0.025, 0.024]`, `lensRadius: 0.0045`, `lensLength: 0.008`, `bracketWidth: 0.010`, `bracketThickness: 0.003`, `bracketFoot: 0.022` |
| `wire` | `radius: 0.00065`, `archHeight: 0.042` |

Deck hole/slot positions, cosmetic component offsets and wire endpoints are
dimensionless proportions of these values. The roller-centre radius is
derived so the capsule tips stay inside `wheel.radius`; wheel width is
derived from its hub and capsule dimensions. Updating `DIMS` and constructing
a fresh model updates the geometry and returned bounds together.
