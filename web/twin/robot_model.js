import * as THREE from 'three';

// Metres, Z-up, +x forward, +y left. Photo estimates except the Pi / AA
// reference dimensions. All physical dimensions live here; see the 1F brief.
export const DIMS = {
  chassis: { length: 0.300, width: 0.150, cornerRadius: 0.035,
    thickness: 0.002, lowerZ: 0.050, upperZ: 0.098,
    slotLength: 0.026, slotWidth: 0.0035, holeRadius: 0.0018,
    standoffRadius: 0.003, boltRadius: 0.0028, boltHeight: 0.002 },
  wheel: { radius: 0.035, base: 0.180, track: 0.174,
    hubRadius: 0.026, hubWidth: 0.020, plateThickness: 0.002,
    coreRadius: 0.011, coreWidth: 0.027, rollerRadius: 0.006,
    rollerStraight: 0.025, rollers: 9, rollerAngleDeg: 45 },
  motor: { radius: 0.012, length: 0.033, gearbox: [0.032, 0.020, 0.023] },
  pcb: { thickness: 0.0016, clearance: 0.004 },
  driver: { size: [0.043, 0.043], centersX: [-0.025, 0.027], y: 0,
    heatsink: [0.023, 0.018, 0.027], finThickness: 0.0015, fins: 6,
    terminal: [0.012, 0.009, 0.010], capRadius: 0.0033, capHeight: 0.012 },
  buck: { size: [0.043, 0.021], center: [-0.074, 0.013],
    inductorRadius: 0.005, inductorHeight: 0.005,
    trimmer: [0.007, 0.007, 0.009] },
  pi: { size: [0.030, 0.065], center: [-0.114, 0],
    chip: [0.010, 0.012, 0.0015], port: [0.007, 0.011, 0.004],
    headerPitch: 0.00254, pinWidth: 0.00065, pinHeight: 0.006,
    headerBaseHeight: 0.0025 },
  battery: { size: [0.036, 0.058, 0.017], center: [0.100, 0.005],
    cellLength: 0.050, cellRadius: 0.007, wall: 0.002, terminalHeight: 0.001 },
  camera: { x: 0.135, height: 0.250, pitchDeg: -10,
    board: [0.0016, 0.025, 0.024], lensRadius: 0.0045, lensLength: 0.008,
    bracketWidth: 0.010, bracketThickness: 0.003, bracketFoot: 0.022 },
  wire: { radius: 0.00065, archHeight: 0.042 },
};

const Y = new THREE.Vector3(0, 1, 0);
const Z = new THREE.Vector3(0, 0, 1);
const TAU = Math.PI * 2;

/** Physical wheel speeds, not normalised robot commands. Positive = forward.
 * At the ground, positive rotation about +y moves the tread toward -x.
 * FL/RR roller axes are +x,+y; FR/RL are +x,-y (the top view is an O).
 */
export function mecanumWheelSpeeds(vx, vy, wz, dims) {
  const k = (dims.wheelBase + dims.trackWidth) / 2;
  const r = dims.wheelRadius;
  return {
    fl: (vx - vy - k * wz) / r,
    fr: (vx + vy + k * wz) / r,
    rl: (vx + vy - k * wz) / r,
    rr: (vx - vy + k * wz) / r,
  };
}

function roundedRect(path, x, y, width, height, radius) {
  const r = Math.min(radius, width / 2, height / 2);
  path.moveTo(x + r, y);
  path.lineTo(x + width - r, y);
  path.quadraticCurveTo(x + width, y, x + width, y + r);
  path.lineTo(x + width, y + height - r);
  path.quadraticCurveTo(x + width, y + height, x + width - r, y + height);
  path.lineTo(x + r, y + height);
  path.quadraticCurveTo(x, y + height, x, y + height - r);
  path.lineTo(x, y + r);
  path.quadraticCurveTo(x, y, x + r, y);
  return path;
}

/** Build an independent, disposable model. No DOM, textures, sockets or assets. */
export function createRobotModel(opts = {}) {
  const d = DIMS;
  const c = d.chassis;
  const w = d.wheel;
  const object = new THREE.Group();
  object.name = 'NeuroMech robot (metres, Z-up)';
  object.up.copy(Z);
  const geometries = new Set();
  const materials = new Set();
  const keep = geometry => { geometries.add(geometry); return geometry; };
  const material = (color, metalness = 0, roughness = 0.55) => {
    const m = new THREE.MeshStandardMaterial({ color, metalness, roughness });
    materials.add(m);
    return m;
  };
  const m = {
    aluminium: material(0xbfc7ce, 0.78, 0.43), brass: material(0xb49a46, 0.72, 0.32),
    yellow: material(0xffcc16, 0.05, 0.35), rubber: material(0x17191c, 0, 0.82),
    black: material(0x22282e, 0.25, 0.47), red: material(0xb82927),
    blue: material(0x1377ce), green: material(0x287f43), gold: material(0xd8b463, 0.75, 0.28),
    cell: material(0xc5ced4, 0.65, 0.30), lens: material(0x102d44, 0.5, 0.12),
  };
  const boxGeometry = keep(new THREE.BoxGeometry(1, 1, 1));
  const cylinderGeometry = keep(new THREE.CylinderGeometry(1, 1, 1, 16));
  const matrixObject = new THREE.Object3D();
  const batches = new Map();

  // Batch repeated parts per geometry/material/parent. The two perforated
  // decks share one geometry, including real holes (not dark decals).
  function part(geometry, mat, position, scale = [1, 1, 1], quaternion = null, parent = object) {
    const key = `${parent.uuid}/${geometry.uuid}/${mat.uuid}`;
    if (!batches.has(key)) batches.set(key, { geometry, mat, parent, matrices: [] });
    matrixObject.position.fromArray(position);
    matrixObject.scale.fromArray(scale);
    matrixObject.quaternion.copy(quaternion || new THREE.Quaternion());
    matrixObject.updateMatrix();
    batches.get(key).matrices.push(matrixObject.matrix.clone());
  }
  function box(mat, size, position, quaternion = null, parent = object) {
    part(boxGeometry, mat, position, size, quaternion, parent);
  }
  function cylinder(mat, radius, length, position, axis = Z, parent = object) {
    part(cylinderGeometry, mat, position, [radius, length, radius],
      new THREE.Quaternion().setFromUnitVectors(Y, axis), parent);
  }

  const deck = roundedRect(new THREE.Shape(), -c.length / 2, -c.width / 2,
    c.length, c.width, c.cornerRadius);
  for (const xFraction of [-0.39, -0.20, 0, 0.20, 0.39]) {
    for (const yFraction of [-0.37, 0.37]) {
      const slot = roundedRect(new THREE.Path(), xFraction * c.length - c.slotLength / 2,
        yFraction * c.width - c.slotWidth / 2, c.slotLength, c.slotWidth, c.slotWidth / 2);
      deck.holes.push(slot);
    }
  }
  for (const xFraction of [-0.40, -0.30, -0.10, 0.10, 0.30, 0.40]) {
    for (const yFraction of [-0.25, 0.25]) {
      const hole = new THREE.Path();
      hole.absarc(xFraction * c.length, yFraction * c.width, c.holeRadius, 0, TAU, true);
      deck.holes.push(hole);
    }
  }
  const deckGeometry = keep(new THREE.ExtrudeGeometry(deck,
    { depth: c.thickness, bevelEnabled: false, curveSegments: 5, steps: 1 }));
  // ExtrudeGeometry otherwise emits two draw calls for the same material.
  deckGeometry.clearGroups();
  for (const z of [c.lowerZ, c.upperZ]) part(deckGeometry, m.aluminium, [0, 0, z]);
  for (const x of [-c.length * 0.37, 0, c.length * 0.37]) {
    for (const y of [-c.width * 0.29, c.width * 0.29]) {
      cylinder(m.brass, c.standoffRadius, c.upperZ - c.lowerZ - c.thickness,
        [x, y, (c.upperZ + c.lowerZ + c.thickness) / 2]);
      cylinder(m.aluminium, c.boltRadius, c.boltHeight,
        [x, y, c.upperZ + c.thickness + c.boltHeight / 2]);
    }
  }

  // Scalloped yellow side plates expose the nine black angled rollers.
  const face = new THREE.Shape();
  for (let i = 0; i <= w.rollers * 8; i++) {
    const angle = i / (w.rollers * 8) * TAU;
    const radius = w.hubRadius * (0.91 + 0.09 * Math.cos(w.rollers * angle));
    if (i === 0) face.moveTo(Math.cos(angle) * radius, Math.sin(angle) * radius);
    else face.lineTo(Math.cos(angle) * radius, Math.sin(angle) * radius);
  }
  const hubHole = new THREE.Path();
  hubHole.absarc(0, 0, w.coreRadius * 0.9, 0, TAU, true);
  face.holes.push(hubHole);
  const faceGeometry = keep(new THREE.ExtrudeGeometry(face,
    { depth: w.plateThickness, bevelEnabled: false, curveSegments: 8 }));
  faceGeometry.clearGroups();
  faceGeometry.translate(0, 0, -w.plateThickness / 2);
  faceGeometry.rotateX(Math.PI / 2);
  const rollerGeometry = keep(new THREE.CapsuleGeometry(w.rollerRadius, w.rollerStraight, 3, 8));
  const tilt = THREE.MathUtils.degToRad(w.rollerAngleDeg);
  // Account for the capsule tips: the rolling envelope, not its centre, is r.
  const rimRadius = Math.sqrt((w.radius - w.rollerRadius) ** 2 -
    (w.rollerStraight * Math.sin(tilt) / 2) ** 2);
  const wheels = {};
  for (const [name, xSign, ySign, handedness] of [
    ['fl', 1, 1, 1], ['fr', 1, -1, -1], ['rl', -1, 1, -1], ['rr', -1, -1, 1],
  ]) {
    const wheel = new THREE.Group();
    wheel.name = `wheel-${name}`;
    wheel.position.set(xSign * w.base / 2, ySign * w.track / 2, w.radius);
    wheel.userData.rollerHandedness = handedness;
    object.add(wheel);
    wheels[name] = wheel;
    for (const side of [-1, 1]) {
      part(faceGeometry, m.yellow, [0, side * w.hubWidth / 2, 0], [1, 1, 1], null, wheel);
    }
    cylinder(m.black, w.coreRadius, w.coreWidth, [0, 0, 0], Y, wheel);
    for (let i = 0; i < w.rollers; i++) {
      // i=0 is at the ground. Tangent +x there, -x at the wheel's top.
      const a = i * TAU / w.rollers;
      const axis = new THREE.Vector3(Math.cos(a) * Math.sin(tilt),
        handedness * Math.cos(tilt), Math.sin(a) * Math.sin(tilt));
      part(rollerGeometry, m.rubber, [Math.sin(a) * rimRadius, 0, -Math.cos(a) * rimRadius],
        [1, 1, 1], new THREE.Quaternion().setFromUnitVectors(Y, axis), wheel);
    }
    cylinder(m.aluminium, d.motor.radius, d.motor.length,
      [wheel.position.x, ySign * (w.track / 2 - w.hubWidth - d.motor.length / 2), w.radius], Y);
    box(m.yellow, d.motor.gearbox,
      [wheel.position.x, ySign * (w.track / 2 - w.hubWidth), w.radius]);
  }

  const pcbZ = c.upperZ + c.thickness + d.pcb.clearance;
  const surfaceZ = pcbZ + d.pcb.thickness;
  function board(mat, size, x, y) {
    box(mat, [...size, d.pcb.thickness], [x, y, pcbZ + d.pcb.thickness / 2]);
    for (const sx of [-1, 1]) for (const sy of [-1, 1]) {
      cylinder(m.brass, c.holeRadius, d.pcb.clearance,
        [x + sx * size[0] * 0.42, y + sy * size[1] * 0.42, pcbZ - d.pcb.clearance / 2]);
    }
  }
  function capacitor(x, y, radius = d.driver.capRadius, height = d.driver.capHeight) {
    cylinder(m.black, radius, height, [x, y, surfaceZ + height / 2]);
    cylinder(m.cell, radius * 0.9, c.thickness / 2, [x, y, surfaceZ + height]);
  }
  for (const x of d.driver.centersX) {
    const y = d.driver.y;
    const [sx, sy, sz] = d.driver.heatsink;
    board(m.red, d.driver.size, x, y);
    box(m.black, [sx, sy, sz * 0.17], [x, y, surfaceZ + sz * 0.085]);
    for (let i = 0; i < d.driver.fins; i++) {
      box(m.black, [d.driver.finThickness, sy, sz],
        [x - sx / 2 + d.driver.finThickness / 2 + i * (sx - d.driver.finThickness) / (d.driver.fins - 1),
          y, surfaceZ + sz / 2]);
    }
    for (const side of [-1, 1]) {
      const ty = y + side * d.driver.size[1] * 0.36;
      box(m.blue, d.driver.terminal, [x, ty, surfaceZ + d.driver.terminal[2] / 2]);
      for (const dx of [-0.25, 0.25]) {
        cylinder(m.aluminium, c.holeRadius, c.boltHeight / 2,
          [x + dx * d.driver.terminal[0], ty, surfaceZ + d.driver.terminal[2]]);
      }
    }
    capacitor(x + d.driver.size[0] * 0.37, y + d.driver.size[1] * 0.28);
    capacitor(x - d.driver.size[0] * 0.37, y - d.driver.size[1] * 0.25);
  }
  const [bx, by] = d.buck.center;
  board(m.blue, d.buck.size, bx, by);
  cylinder(m.black, d.buck.inductorRadius, d.buck.inductorHeight,
    [bx, by, surfaceZ + d.buck.inductorHeight / 2]);
  cylinder(m.brass, d.buck.inductorRadius * 0.62, d.buck.inductorHeight,
    [bx, by, surfaceZ + d.buck.inductorHeight / 2]);
  box(m.blue, d.buck.trimmer, [bx - d.buck.size[0] * 0.31, by, surfaceZ + d.buck.trimmer[2] / 2]);
  cylinder(m.brass, c.holeRadius, c.boltHeight,
    [bx - d.buck.size[0] * 0.31, by, surfaceZ + d.buck.trimmer[2]]);
  capacitor(bx + d.buck.size[0] * 0.32, by);

  const [px, py] = d.pi.center;
  board(m.green, d.pi.size, px, py);
  box(m.black, d.pi.chip, [px, py, surfaceZ + d.pi.chip[2] / 2]);
  const headerX = px - d.pi.size[0] * 0.34;
  box(m.black, [d.pi.headerPitch * 2, d.pi.headerPitch * 20, d.pi.headerBaseHeight],
    [headerX, py, surfaceZ + d.pi.headerBaseHeight / 2]);
  for (const row of [-0.5, 0.5]) for (let i = 0; i < 20; i++) {
    box(m.gold, [d.pi.pinWidth, d.pi.pinWidth, d.pi.pinHeight],
      [headerX + row * d.pi.headerPitch, py + (i - 9.5) * d.pi.headerPitch,
        surfaceZ + d.pi.headerBaseHeight + d.pi.pinHeight / 2]);
  }
  for (const offset of [-0.28, 0.05, 0.32]) {
    box(m.aluminium, d.pi.port,
      [px + d.pi.size[0] * 0.43, py + offset * d.pi.size[1], surfaceZ + d.pi.port[2] / 2]);
  }

  const b = d.battery;
  const [ax, ay] = b.center;
  const floorZ = c.upperZ + c.thickness;
  box(m.black, [b.size[0], b.size[1], b.wall], [ax, ay, floorZ + b.wall / 2]);
  for (const side of [-1, 1]) {
    box(m.black, [b.wall, b.size[1], b.size[2]],
      [ax + side * (b.size[0] - b.wall) / 2, ay, floorZ + b.size[2] / 2]);
    box(m.black, [b.size[0], b.wall, b.size[2]],
      [ax, ay + side * (b.size[1] - b.wall) / 2, floorZ + b.size[2] / 2]);
    const cellX = ax + side * b.size[0] * 0.22;
    const cellZ = floorZ + b.wall + b.cellRadius;
    cylinder(m.cell, b.cellRadius, b.cellLength, [cellX, ay, cellZ], Y);
    cylinder(m.black, b.cellRadius * 1.01, b.cellLength * 0.54, [cellX, ay, cellZ], Y);
    cylinder(m.brass, b.cellRadius * 0.45, b.terminalHeight,
      [cellX, ay + side * (b.cellLength + b.terminalHeight) / 2, cellZ], Y);
  }

  const height = Number.isFinite(opts.camera?.height_m) ? opts.camera.height_m : d.camera.height;
  const pitchDeg = Number.isFinite(opts.camera?.pitch_deg) ? opts.camera.pitch_deg : d.camera.pitchDeg;
  const cameraMount = { position: [d.camera.x, 0, height], pitchDeg };
  const cameraRig = new THREE.Group();
  cameraRig.name = 'camera-prop';
  cameraRig.position.fromArray(cameraMount.position);
  // Positive pitch looks up; a THREE +y rotation tilts +x downward.
  cameraRig.rotation.y = -THREE.MathUtils.degToRad(pitchDeg);
  object.add(cameraRig);
  const cam = d.camera;
  box(m.green, cam.board, [-cam.lensLength - cam.board[0] / 2, 0, 0], null, cameraRig);
  cylinder(m.black, cam.lensRadius, cam.lensLength,
    [-cam.lensLength / 2, 0, 0], new THREE.Vector3(1, 0, 0), cameraRig);
  cylinder(m.lens, cam.lensRadius * 0.78, cam.board[0] / 4,
    [0, 0, 0], new THREE.Vector3(1, 0, 0), cameraRig);
  const bracketTop = Math.max(floorZ, height);
  box(m.aluminium, [cam.bracketThickness, cam.bracketWidth, Math.max(cam.bracketThickness, bracketTop - floorZ)],
    [cam.x - cam.lensLength - cam.board[0] - cam.bracketThickness, 0, (floorZ + bracketTop) / 2]);
  box(m.aluminium, [cam.bracketFoot, cam.bracketWidth, cam.bracketThickness],
    [cam.x - cam.bracketFoot / 2, 0, floorZ + cam.bracketThickness / 2]);

  for (const [start, end, color, lift] of [
    [[px, py, surfaceZ], [d.driver.centersX[0], -d.driver.size[1] / 2, surfaceZ], 0xf1c62e, 1],
    [[px, py + d.pi.headerPitch * 2, surfaceZ], [d.driver.centersX[0], -d.driver.size[1] / 2, surfaceZ], 0x41b893, 0.91],
    [[bx, by, surfaceZ], [d.driver.centersX[1], d.driver.size[1] / 2, surfaceZ], 0x5089df, 0.85],
    [[ax, ay - b.size[1] / 2, surfaceZ], [d.driver.centersX[1], -d.driver.size[1] / 2, surfaceZ], 0xe14540, 0.4],
    [[ax, ay - b.size[1] / 2, surfaceZ], [bx, by - d.buck.size[1] / 2, surfaceZ], 0x21252a, 0.55],
  ]) {
    const a = new THREE.Vector3(...start);
    const z = new THREE.Vector3(...end);
    const mid = a.clone().lerp(z, 0.5);
    mid.z += d.wire.archHeight * lift;
    const curve = new THREE.CatmullRomCurve3([a, mid, z]);
    const geometry = keep(new THREE.TubeGeometry(curve, 12, d.wire.radius, 5, false));
    part(geometry, material(color), [0, 0, 0]);
  }

  for (const { geometry, mat, parent, matrices } of batches.values()) {
    const mesh = new THREE.InstancedMesh(geometry, mat, matrices.length);
    matrices.forEach((matrix, index) => mesh.setMatrixAt(index, matrix));
    mesh.instanceMatrix.needsUpdate = true;
    mesh.castShadow = mesh.receiveShadow = true;
    parent.add(mesh);
  }
  // Wheel bounds use the full continuous rolling envelope. The camera may
  // extend beyond the chassis when callers choose a different pitch/height.
  object.updateMatrixWorld(true);
  const cameraBounds = new THREE.Box3().setFromObject(cameraRig);
  const wheelWidth = Math.max(w.coreWidth, w.hubWidth + w.plateThickness,
    w.rollerStraight * Math.cos(tilt) + 2 * w.rollerRadius);
  const halfLength = Math.max(c.length / 2, w.base / 2 + w.radius,
    Math.abs(cameraBounds.min.x), Math.abs(cameraBounds.max.x));
  const halfWidth = Math.max(c.width / 2, (w.track + wheelWidth) / 2, cam.board[1] / 2);
  const dims = {
    length: halfLength * 2, width: halfWidth * 2,
    height: Math.max(cameraBounds.max.z, c.upperZ + c.thickness + d.pcb.clearance +
      d.pcb.thickness + Math.max(d.driver.heatsink[2], d.wire.archHeight), w.radius * 2),
    wheelRadius: w.radius, wheelBase: w.base, trackWidth: w.track,
    footprintRadius: Math.hypot(halfLength, halfWidth),
  };
  let disposed = false;
  return {
    object, dims, cameraMount,
    update(dt, wheelRadPerSec = {}) {
      if (disposed || !Number.isFinite(dt) || dt <= 0) return;
      for (const name of Object.keys(wheels)) {
        const speed = wheelRadPerSec[name];
        if (Number.isFinite(speed)) wheels[name].rotation.y = (wheels[name].rotation.y + speed * dt) % TAU;
      }
    },
    setHighlight(color) {
      const active = color != null;
      for (const mat of [m.aluminium, m.yellow]) {
        mat.emissive.set(active ? color : 0x000000);
        mat.emissiveIntensity = active ? 0.24 : 0;
      }
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      object.removeFromParent();
      object.traverse(node => { if (node.isInstancedMesh) node.dispose(); });
      for (const geometry of geometries) geometry.dispose();
      for (const mat of materials) mat.dispose();
    },
  };
}
