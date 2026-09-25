// 3D virtual sim. This page IS the virtual robot on /ws/robot: it applies
// the hub's cmds, collides with the arena, streams its first-person camera
// as the video feed, and shows the brain-control state in 3D.
// URL params: ?embed=1 (compact, for the dashboard iframe), ?mode=view
// (watch only, don't connect as the robot), ?world=<name>, ?hub=host:port.
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { loadWorld, buildWorld } from "./world.js";
import { step } from "./physics.js";
import { RobotLink, DashLink, hubBase } from "./net.js";
import { FpvCamera } from "./fpv.js";
import { RobotHud3D, HudOverlay } from "./hud.js";

// Z-up world. Must be set before any Object3D is created.
THREE.Object3D.DEFAULT_UP.set(0, 0, 1);

const params = new URLSearchParams(location.search);
const EMBED = params.get("embed") === "1";
const VIEW_ONLY = params.get("mode") === "view";
const FORWARD_KEYS = new Set(["Escape", " ", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight",
  "w", "a", "s", "d", "W", "A", "S", "D", "1", "2", "3", "4", "0"]);
const TELEMETRY_MS = 100;
const MAX_DT = 0.1;            // s: longer gaps (tab was hidden) aren't integrated
const TRAIL_POINTS = 2000;

document.body.classList.toggle("embed", EMBED);

// 1F's model if it loads, else a placeholder behind the same interface.
async function loadRobotModule() {
  try {
    const mod = await import("./robot_model.js");
    if (typeof mod.createRobotModel === "function" && typeof mod.mecanumWheelSpeeds === "function") return { mod, placeholder: false };
    throw new Error("robot_model.js is missing an export");
  } catch (e) {
    console.warn("robot_model.js unavailable, using placeholder:", e.message);
    return { mod: await import("./placeholder_robot.js"), placeholder: true };
  }
}

function showFatal(msg) {
  const el = document.getElementById("banner");
  el.textContent = msg;
  el.className = "banner bad";
}

async function main() {
  const worldName = (params.get("world") || "default").replace(/[^\w-]/g, "");
  const [world, robotMod] = await Promise.all([loadWorld(`./worlds/${worldName}.json`), loadRobotModule()]);
  const camCfg = world.robot.camera;

  // --- renderer and scene -------------------------------------------------
  const canvas = document.getElementById("view");
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x1d2127);
  scene.add(new THREE.HemisphereLight(0xdfe8ff, 0x3a3226, 1.4));
  const sun = new THREE.DirectionalLight(0xffffff, 2.2);
  const [sx, sy] = world.arena.size;
  sun.position.set(-2, -3, 6);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  const ext = Math.max(sx, sy) / 2 + 0.5;
  Object.assign(sun.shadow.camera, { left: -ext, right: ext, top: ext, bottom: -ext, near: 1, far: 15 });
  sun.shadow.bias = -0.0005;
  sun.shadow.normalBias = 0.02;
  scene.add(sun);

  const arena = buildWorld(scene, world);

  // --- robot --------------------------------------------------------------
  // poseGroup carries the world pose (x, y, heading); the model, HUD marks
  // and FPV camera hang off it in the robot frame.
  const model = robotMod.mod.createRobotModel({ camera: camCfg });
  const dims = model.dims;
  const radius = dims.footprintRadius || world.robot.radius || 0.15;
  const poseGroup = new THREE.Group();
  poseGroup.add(model.object);
  model.object.traverse((o) => { if (o.isMesh) { o.castShadow = true; o.receiveShadow = true; } });
  scene.add(poseGroup);
  const hud3d = new RobotHud3D({ ...dims, footprintRadius: radius });
  poseGroup.add(hud3d.object);

  const pose = { x: world.spawn.x, y: world.spawn.y, heading: world.spawn.heading || 0 };
  const maxSpeed = world.robot.max_speed_mps || 0.5;
  const motion = { vx: 0, vy: 0, watchdog: true, collision: false };

  // --- trail --------------------------------------------------------------
  const trailPos = new Float32Array(TRAIL_POINTS * 3);
  const trailGeo = new THREE.BufferGeometry();
  trailGeo.setAttribute("position", new THREE.BufferAttribute(trailPos, 3).setUsage(THREE.DynamicDrawUsage));
  trailGeo.setDrawRange(0, 0);
  const trail = new THREE.Line(trailGeo, new THREE.LineBasicMaterial({ color: 0x36a3ff, transparent: true, opacity: 0.8 }));
  trail.frustumCulled = false;
  scene.add(trail);
  let trailN = 0;
  function pushTrail(x, y) {
    if (trailN > 0) {
      const i = (trailN - 1) * 3;
      if (Math.hypot(x - trailPos[i], y - trailPos[i + 1]) < 0.02) return;
    }
    if (trailN === TRAIL_POINTS) { trailPos.copyWithin(0, 3); trailN--; }
    trailPos.set([x, y, 0.006], trailN * 3);
    trailN++;
    trailGeo.setDrawRange(0, trailN);
    trailGeo.attributes.position.needsUpdate = true;
  }
  pushTrail(pose.x, pose.y);

  // --- FPV camera = the video feed ----------------------------------------
  const fpv = new FpvCamera({ scene, robotGroup: poseGroup, cam: camCfg, mount: model.cameraMount });
  const pip = document.getElementById("pip");
  pip.appendChild(fpv.canvas);

  // --- main view cameras --------------------------------------------------
  const camera = new THREE.PerspectiveCamera(55, 1, 0.02, 100);
  const orbit = new OrbitControls(camera, canvas);
  orbit.enableDamping = true;
  orbit.enabled = false;
  const CAM_MODES = ["chase", "top", "orbit"];
  let camMode = params.get("cam") && CAM_MODES.includes(params.get("cam")) ? params.get("cam") : "chase";
  const chaseTarget = new THREE.Vector3();
  const chasePos = new THREE.Vector3();
  function setCamMode(m) {
    camMode = m;
    orbit.enabled = m === "orbit";
    if (m === "orbit") {
      orbit.target.set(pose.x, pose.y, 0.1);
      camera.position.set(pose.x - 1.6, pose.y - 1.6, 1.4);
    }
    // Top view: x to the right, y (left) up the screen, like a map.
    if (m === "top") camera.up.set(0, 1, 0); else camera.up.set(0, 0, 1);
    placeCamera(1);
  }
  function placeCamera(alpha) {
    const c = Math.cos(pose.heading), s = Math.sin(pose.heading);
    if (camMode === "chase") {
      // Behind and above, but kept inside the arena so the perimeter wall
      // never blocks the view near the edges.
      chasePos.set(
        THREE.MathUtils.clamp(pose.x - 0.9 * c, -sx / 2 + 0.05, sx / 2 - 0.05),
        THREE.MathUtils.clamp(pose.y - 0.9 * s, -sy / 2 + 0.05, sy / 2 - 0.05), 0.75);
      chaseTarget.set(pose.x + 0.4 * c, pose.y + 0.4 * s, 0.05);
      camera.position.lerp(chasePos, alpha);
      camera.lookAt(chaseTarget);
    } else if (camMode === "top") {
      // Whole arena from above.
      const fitW = sx + 0.6, fitH = sy + 0.6;
      const vfov = THREE.MathUtils.degToRad(camera.fov);
      const dist = Math.max(fitH, fitW / camera.aspect) / 2 / Math.tan(vfov / 2);
      camera.position.set(0, 0, dist);
      camera.lookAt(0, 0, 0);
    } else {
      orbit.update();
    }
  }
  function resize() {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    if (camMode === "top") placeCamera(1);
  }
  new ResizeObserver(resize).observe(canvas);
  resize();
  setCamMode(camMode);

  // --- hub links ----------------------------------------------------------
  const base = hubBase();
  const hud = new HudOverlay(document.getElementById("hud"));
  const dash = new DashLink({ url: `${base}/ws/dashboard` });
  dash.start();
  const robot = new RobotLink({
    url: `${base}/ws/robot`,
    video: { w: fpv.w, h: fpv.h, fps: 20 },
    onStatus: updateBanner,
  });

  // Two sim tabs in one browser would fight over /ws/robot. The newest tab
  // takes the slot and tells the others to let go.
  const bc = "BroadcastChannel" in window ? new BroadcastChannel("neuromech-twin") : null;
  const tabId = Math.random().toString(36).slice(2);
  function claimRobot() {
    bc?.postMessage({ type: "claim", from: tabId });
    robot.start();
    updateBanner();
  }
  if (bc) bc.onmessage = (ev) => {
    if (ev.data?.type === "claim" && ev.data.from !== tabId && robot.enabled) robot.stop("another sim tab is the robot");
  };
  document.getElementById("takeover").addEventListener("click", claimRobot);
  if (!VIEW_ONLY) claimRobot(); else updateBanner();

  function updateBanner() {
    const el = document.getElementById("banner");
    const btn = document.getElementById("takeover");
    let msg = "", cls = "";
    if (document.hidden) {
      msg = "Sim hidden: physics and video paused. Keep this tab visible."; cls = "bad";
    } else if (VIEW_ONLY) {
      msg = "View only: not connected as the robot."; cls = "dim";
    } else if (!robot.enabled) {
      msg = `Not the robot: ${robot.stoppedReason}.`; cls = "warn";
    } else if (!robot.connected) {
      msg = "Connecting to hub as the robot…"; cls = "warn";
    } else if (robotMod.placeholder) {
      msg = "Placeholder robot (robot_model.js not loaded)."; cls = "dim";
    }
    el.textContent = msg;
    el.className = "banner " + cls;
    btn.hidden = VIEW_ONLY ? false : robot.enabled;
    btn.textContent = VIEW_ONLY ? "Be the robot" : "Take over as robot";
  }

  // Telemetry at 10 Hz from a timer, so the hub still hears from us (at the
  // browser's throttled rate) even while the tab is hidden.
  setInterval(() => {
    if (!robot.connected) return;
    robot.sendJson({
      type: "telemetry",
      vx: round3(motion.vx), vy: round3(motion.vy),
      watchdog_stopped: motion.watchdog,
      battery_v: null,
      x: round3(pose.x), y: round3(pose.y), heading: round3(pose.heading),
      collision: motion.collision,
      sim_hidden: document.hidden,          // additive: physics paused
    });
  }, TELEMETRY_MS);

  // --- hidden tab handling ------------------------------------------------
  let hiddenAt = 0;
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) hiddenAt = performance.now();
    else if (hiddenAt) console.warn(`sim was hidden for ${((performance.now() - hiddenAt) / 1000).toFixed(1)} s`);
    updateBanner();
  });

  // --- keys ---------------------------------------------------------------
  const inIframe = window.parent !== window;
  function onKey(ev) {
    const key = ev.key;
    if (ev.type === "keydown" && (key === "c" || key === "C") && !ev.repeat) {
      setCamMode(CAM_MODES[(CAM_MODES.indexOf(camMode) + 1) % CAM_MODES.length]);
      return;
    }
    if (!FORWARD_KEYS.has(key)) return;
    if (inIframe) {
      window.parent.postMessage({ type: "twin-key", event: ev.type, key }, "*");
      ev.preventDefault();       // no page scroll on arrows/space
    }
  }
  window.addEventListener("keydown", onKey);
  window.addEventListener("keyup", onKey);

  // --- main loop ----------------------------------------------------------
  let last = performance.now();
  let hudAt = 0, lastState = null, lastCollision = false;
  let fpsN = 0, fpsT0 = last, mainFps = 0;
  function frame(now) {
    requestAnimationFrame(frame);
    const dt = Math.min(MAX_DT, Math.max(0, (now - last) / 1000));
    last = now;

    // Watchdog lives in robot.command(): stale cmd -> zero velocity.
    const c = VIEW_ONLY ? { vx: 0, vy: 0, watchdog: true } : robot.command(now);
    motion.vx = c.vx; motion.vy = c.vy; motion.watchdog = c.watchdog;
    const vxm = c.vx * maxSpeed, vym = c.vy * maxSpeed;
    motion.collision = step(pose, vxm, vym, dt, radius, arena.colliders);
    poseGroup.position.set(pose.x, pose.y, 0);
    poseGroup.rotation.z = pose.heading;
    model.update(dt, robotMod.mod.mecanumWheelSpeeds(vxm, vym, 0, dims));
    pushTrail(pose.x, pose.y);

    const st = dash.state;
    if (st !== lastState) { hud3d.update(st); lastState = st; }
    if (motion.collision !== lastCollision) {
      lastCollision = motion.collision;
      model.setHighlight?.(motion.collision ? 0xff3020 : null);
    }

    if (camMode !== "top") placeCamera(camMode === "chase" ? 1 - Math.exp(-dt * 6) : 1);
    renderer.render(scene, camera);

    if (!VIEW_ONLY) fpv.tick(now, () => robot.canSendFrame(), (buf) => robot.sendFrame(buf));
    else fpv.tick(now, () => false, () => false);

    fpsN++;
    if (now - fpsT0 >= 1000) { mainFps = (fpsN * 1000) / (now - fpsT0); fpsN = 0; fpsT0 = now; }
    if (now - hudAt > 100) {
      hudAt = now;
      hud.update({ state: st, dashConnected: dash.connected, robot, motion, fpv, camMode, paused: document.hidden });
      document.getElementById("mainfps").textContent = `${mainFps.toFixed(0)} fps`;
      const ps = document.getElementById("pose");
      ps.textContent = `x ${pose.x.toFixed(2)}  y ${pose.y.toFixed(2)}`;
    }
  }
  requestAnimationFrame(frame);

  // For debugging from the console and for automated tests.
  window.twin = { pose, motion, robot, dash, fpv, setCamMode, model, world };
}

function round3(v) { return Math.round(v * 1000) / 1000; }

main().catch((e) => { console.error(e); showFatal(`Sim failed to start: ${e.message}`); });
