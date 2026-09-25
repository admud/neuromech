// Kinematic robot: a circle of radius r moving in the plane, pushed out of
// oriented boxes. Pushing out along the contact normal cancels only the
// into-wall part of the motion, so the robot slides along walls.

const CONTACT_EPS = 0.002;   // m: within this of a wall counts as touching

/** Push point (px, py) with radius r out of every collider. Returns
 *  {x, y, hit}. A few passes handle corners where two boxes meet. */
export function resolve(px, py, r, colliders) {
  let hit = false;
  for (let pass = 0; pass < 4; pass++) {
    let moved = false;
    for (const b of colliders) {
      // Circle centre in the box's local frame.
      const dx = px - b.x, dy = py - b.y;
      const lx = b.c * dx + b.s * dy;
      const ly = -b.s * dx + b.c * dy;
      const qx = Math.max(-b.hw, Math.min(b.hw, lx));
      const qy = Math.max(-b.hd, Math.min(b.hd, ly));
      let nx = lx - qx, ny = ly - qy;
      let dist = Math.hypot(nx, ny);
      if (dist >= r + CONTACT_EPS) continue;
      hit = true;
      if (dist >= r) continue;         // touching, not penetrating
      if (dist < 1e-9) {
        // Centre inside the box: leave by the nearest face.
        const ox = b.hw - Math.abs(lx), oy = b.hd - Math.abs(ly);
        if (ox < oy) { nx = Math.sign(lx) || 1; ny = 0; dist = -ox; }
        else { nx = 0; ny = Math.sign(ly) || 1; dist = -oy; }
      } else {
        nx /= dist; ny /= dist;
      }
      const push = r - dist;
      const wx = b.c * nx - b.s * ny, wy = b.s * nx + b.c * ny;   // back to world
      px += wx * push; py += wy * push;
      moved = true;
    }
    if (!moved) break;
  }
  return { x: px, y: py, hit };
}

/** Advance the pose by robot-frame velocity (m/s) for dt seconds.
 *  Sub-steps keep a fast robot from tunnelling through thin walls. */
export function step(pose, vxm, vym, dt, r, colliders) {
  const c = Math.cos(pose.heading), s = Math.sin(pose.heading);
  const wx = c * vxm - s * vym, wy = s * vxm + c * vym;
  const dist = Math.hypot(wx, wy) * dt;
  const n = Math.max(1, Math.ceil(dist / (r * 0.25)));
  let hit = false;
  for (let i = 0; i < n; i++) {
    const res = resolve(pose.x + (wx * dt) / n, pose.y + (wy * dt) / n, r, colliders);
    pose.x = res.x; pose.y = res.y;
    hit = hit || res.hit;
  }
  return hit;
}
