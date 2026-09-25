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
   - Roller handedness must match `mecanumWheelSpeeds`: the
     **ground-contact** rollers of FL and RR run along the forward-left
     diagonal, and those of FR and RL along the forward-right diagonal. Seen
     from above, the top rollers then make a diamond ("O") pattern. The
     behaviour in the acceptance list is the real test.
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
- [ ] Recognisably the robot in the photo (chassis shape, yellow mecanum wheels, red driver board, Pi Zero)
- [ ] Z-up, metres, +x forward, origin on the ground; `dims` and `cameraMount` accurate to the `DIMS` values
- [ ] In `model.html`: forward spins all wheels forward; strafe left spins FL/RR backward and FR/RL forward, with the rollers visibly angled consistently with that
- [ ] Within the draw-call/triangle budget; no external assets
- [ ] Handoff notes list every `DIMS` value and whether it was measured or estimated
- [ ] Committed, @main tagged

## Handoff notes
_(fill in when done)_
