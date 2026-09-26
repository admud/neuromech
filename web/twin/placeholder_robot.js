// Stand-in for robot_model.js (1F) with the same interface, used only if
// that module fails to load. A box on four wheels: enough to drive and to
// see the wheels spin the right way.
import * as THREE from "three";

export function mecanumWheelSpeeds(vx, vy, wz, dims) {
  // Same formula as the 1F contract (vy left+, wz CCW+), rad/s per wheel.
  const k = (dims.wheelBase + dims.trackWidth) / 2;
  const r = dims.wheelRadius;
  return {
    fl: (vx - vy - k * wz) / r,
    fr: (vx + vy + k * wz) / r,
    rl: (vx + vy - k * wz) / r,
    rr: (vx - vy + k * wz) / r,
  };
}

export function createRobotModel(opts = {}) {
  const cam = opts.camera || { height_m: 0.25, pitch_deg: -10 };
  const dims = {
    length: 0.22, width: 0.20, height: 0.12,
    wheelRadius: 0.04, wheelBase: 0.15, trackWidth: 0.19,
    footprintRadius: 0.15,
  };
  const object = new THREE.Group();
  object.name = "placeholder-robot";

  const bodyMat = new THREE.MeshStandardMaterial({ color: 0xb8bcc2, metalness: 0.6, roughness: 0.4 });
  const body = new THREE.Mesh(new THREE.BoxGeometry(dims.length, dims.width - 0.06, 0.05), bodyMat);
  body.position.z = dims.wheelRadius + 0.02;
  body.castShadow = body.receiveShadow = true;
  object.add(body);

  // Front marker so forward is obvious.
  const nose = new THREE.Mesh(new THREE.BoxGeometry(0.03, 0.08, 0.02),
    new THREE.MeshStandardMaterial({ color: 0xd03030 }));
  nose.position.set(dims.length / 2 - 0.015, 0, body.position.z + 0.035);
  object.add(nose);

  // Wheels: cylinder axis along y. A stripe makes rotation visible.
  const wheelGeo = new THREE.CylinderGeometry(dims.wheelRadius, dims.wheelRadius, 0.03, 20);
  const wheelMat = new THREE.MeshStandardMaterial({ color: 0xf2c200, roughness: 0.6 });
  const stripeGeo = new THREE.BoxGeometry(0.006, 0.032, dims.wheelRadius * 1.9);
  const stripeMat = new THREE.MeshStandardMaterial({ color: 0x202020 });
  const wheels = {};
  for (const [id, sx, sy] of [["fl", 1, 1], ["fr", 1, -1], ["rl", -1, 1], ["rr", -1, -1]]) {
    const hub = new THREE.Group();
    hub.position.set(sx * dims.wheelBase / 2, sy * dims.trackWidth / 2, dims.wheelRadius);
    const spin = new THREE.Group();   // rotates about y (the axle)
    const w = new THREE.Mesh(wheelGeo, wheelMat);
    w.castShadow = true;
    spin.add(w, new THREE.Mesh(stripeGeo, stripeMat));
    hub.add(spin);
    object.add(hub);
    wheels[id] = spin;
  }

  const cameraMount = { position: [dims.length / 2, 0, cam.height_m], pitchDeg: cam.pitch_deg };
  const camProp = new THREE.Mesh(new THREE.BoxGeometry(0.02, 0.03, 0.03),
    new THREE.MeshStandardMaterial({ color: 0x222222 }));
  camProp.position.set(...cameraMount.position);
  object.add(camProp);

  return {
    object, dims, cameraMount,
    update(dt, w) {
      // Positive rad/s = rolling forward (+x). With the axle along +y,
      // rolling forward is a positive rotation about +y.
      for (const id of ["fl", "fr", "rl", "rr"]) wheels[id].rotation.y += (w[id] || 0) * dt;
    },
    setHighlight(color) {
      bodyMat.emissive.set(color == null ? 0x000000 : color);
      bodyMat.emissiveIntensity = color == null ? 0 : 0.35;
    },
    dispose() {
      object.traverse((o) => { if (o.geometry) o.geometry.dispose(); if (o.material) o.material.dispose(); });
    },
  };
}
