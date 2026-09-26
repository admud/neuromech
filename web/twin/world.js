// Builds the arena from a world file (schema in plan/protocol.md) and
// returns the collision boxes. Z-up, metres, x forward, y left.
import * as THREE from "three";

export async function loadWorld(url) {
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`world ${url}: HTTP ${res.status}`);
  return res.json();
}

// Floor texture drawn in code (no assets): 0.5 m tiles with 0.1 m lines, so
// the FPV camera shows motion clearly and distance is readable.
function floorTexture(sizeX, sizeY) {
  const px = 256;                       // pixels per 0.5 m tile
  const c = document.createElement("canvas");
  c.width = c.height = px;
  const g = c.getContext("2d");
  g.fillStyle = "#d9d6cf"; g.fillRect(0, 0, px, px);
  g.strokeStyle = "#c4c0b6"; g.lineWidth = 2;
  for (let i = 1; i < 5; i++) {
    const p = (i * px) / 5;
    g.beginPath(); g.moveTo(p, 0); g.lineTo(p, px); g.moveTo(0, p); g.lineTo(px, p); g.stroke();
  }
  g.strokeStyle = "#8f8a80"; g.lineWidth = 6; g.strokeRect(0, 0, px, px);
  const tex = new THREE.CanvasTexture(c);
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.repeat.set(sizeX / 0.5, sizeY / 0.5);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 8;
  return tex;
}

/** Adds the arena to `scene`. Returns {boxes, bounds, goal}. */
export function buildWorld(scene, world) {
  const [sx, sy] = world.arena.size;
  const wallH = world.arena.wall_h ?? 0.3;
  const wallT = world.arena.wall_t ?? 0.1;
  const group = new THREE.Group();
  group.name = "world";
  scene.add(group);

  const floor = new THREE.Mesh(
    new THREE.PlaneGeometry(sx + 2 * wallT, sy + 2 * wallT),
    new THREE.MeshStandardMaterial({ map: floorTexture(sx + 2 * wallT, sy + 2 * wallT), roughness: 0.9 }));
  floor.receiveShadow = true;
  group.add(floor);

  // Area outside the arena, so the chase camera never looks into the void.
  const outside = new THREE.Mesh(new THREE.PlaneGeometry(60, 60),
    new THREE.MeshStandardMaterial({ color: 0x3a3f47, roughness: 1 }));
  outside.position.z = -0.002;
  outside.receiveShadow = true;
  group.add(outside);

  // Every box, perimeter included, in one list: {x, y, w, d, h, yaw_deg, color}.
  // The perimeter is implicit from arena.size so the world file stays short.
  const boxes = [
    { x: 0, y: sy / 2 + wallT / 2, w: sx + 2 * wallT, d: wallT, h: wallH, yaw_deg: 0, color: "#9aa0a8" },
    { x: 0, y: -sy / 2 - wallT / 2, w: sx + 2 * wallT, d: wallT, h: wallH, yaw_deg: 0, color: "#9aa0a8" },
    { x: sx / 2 + wallT / 2, y: 0, w: wallT, d: sy, h: wallH, yaw_deg: 0, color: "#9aa0a8" },
    { x: -sx / 2 - wallT / 2, y: 0, w: wallT, d: sy, h: wallH, yaw_deg: 0, color: "#9aa0a8" },
    ...(world.walls || []),
  ];

  const boxGeo = new THREE.BoxGeometry(1, 1, 1);
  const mats = new Map();
  const colliders = [];
  for (const b of boxes) {
    const color = b.color || "#8a9099";
    if (!mats.has(color)) mats.set(color, new THREE.MeshStandardMaterial({ color, roughness: 0.7 }));
    const m = new THREE.Mesh(boxGeo, mats.get(color));
    m.scale.set(b.w, b.d, b.h);
    m.position.set(b.x, b.y, b.h / 2);
    m.rotation.z = THREE.MathUtils.degToRad(b.yaw_deg || 0);
    m.castShadow = m.receiveShadow = true;
    group.add(m);
    const yaw = THREE.MathUtils.degToRad(b.yaw_deg || 0);
    colliders.push({ x: b.x, y: b.y, hw: b.w / 2, hd: b.d / 2, c: Math.cos(yaw), s: Math.sin(yaw) });
  }

  // Optional goal pad (additive world-file field): a target to drive to.
  let goal = null;
  if (world.goal) {
    goal = world.goal;
    const pad = new THREE.Mesh(new THREE.CircleGeometry(goal.r, 48),
      new THREE.MeshStandardMaterial({ color: 0x2fb86b, emissive: 0x1a6b3e, emissiveIntensity: 0.4 }));
    pad.position.set(goal.x, goal.y, 0.002);
    pad.receiveShadow = true;
    group.add(pad);
    const post = new THREE.Mesh(new THREE.CylinderGeometry(0.015, 0.015, 0.5, 10),
      new THREE.MeshStandardMaterial({ color: 0xeeeeee }));
    post.rotation.x = Math.PI / 2;   // cylinder is y-up by default; stand it on z
    post.position.set(goal.x, goal.y, 0.25);
    const flag = new THREE.Mesh(new THREE.BoxGeometry(0.004, 0.14, 0.09),
      new THREE.MeshStandardMaterial({ color: 0x2fb86b }));
    flag.position.set(goal.x, goal.y + 0.07, 0.45);
    post.castShadow = flag.castShadow = true;
    group.add(post, flag);
  }

  return { colliders, bounds: { sx, sy }, goal, group };
}
