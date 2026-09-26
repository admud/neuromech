import { openPage, hubWatcher, sleep } from "./cdp.mjs";
import { execSync, spawn } from "node:child_process";
const HUB = process.env.HUB || "127.0.0.1:18931";
import { REPO } from "./cdp.mjs";
const out = (k, v) => console.log(k.padEnd(48), typeof v === "string" ? v : JSON.stringify(v));

// ---- 1. look-away creep vs margin (no browser needed; command is computed without a robot)
let hub = await hubWatcher(HUB);
hub.send({ type: "arm", armed: true }); await hub.waitFor((s) => s.armed, 3000);
hub.send({ type: "sim_gaze", target: null });
for (const margin of [0.06, 0.08, 0.10]) {
  hub.send({ type: "set_config", margin }); await sleep(3500);  // new decoder window fills
  let moving = 0, n = 0, episodes = 0, prev = false;
  const t0 = Date.now();
  while (Date.now() - t0 < 20000) { const m = !!hub.state.command?.direction; moving += m; n++; if (m && !prev) episodes++; prev = m; await sleep(100); }
  out(`look-away false motion @ margin ${margin}`, `${(100 * moving / n).toFixed(1)}% of time, ${episodes} episodes / 20 s`);
}
// responsiveness at 0.10: gaze up -> command up
hub.send({ type: "sim_gaze", target: "up" });
out("gaze->up latency @ margin 0.10 (s)", await hub.waitFor((s) => s.command?.direction === "up", 10000));
hub.send({ type: "sim_gaze", target: null });
out("look-away->stop latency @ margin 0.10 (s)", await hub.waitFor((s) => !s.command?.direction, 10000));
hub.send({ type: "set_config", margin: 0.06 });

// ---- 2. Esc pressed inside the twin iframe -> dashboard STOP
const dash = await openPage(`http://${HUB}/dashboard/`, 19261, { w: 1600, h: 950 });
await sleep(6000);
hub.send({ type: "arm", armed: true }); await hub.waitFor((s) => s.armed, 3000);
await dash.ev(`(() => { const w = document.querySelector('iframe').contentWindow; w.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', code: 'Escape', bubbles: true})); w.dispatchEvent(new KeyboardEvent('keyup', {key: 'Escape', code: 'Escape', bubbles: true})); return true; })()`);
out("Esc inside sim iframe -> disarm (s)", await hub.waitFor((s) => !s.armed, 2000));

// ---- 3. hub dies while the virtual robot is driving -> robot stops by itself
hub.send({ type: "arm", armed: true }); await hub.waitFor((s) => s.armed, 3000);
const drive = setInterval(() => hub.send({ type: "override", direction: "down" }), 150);
await sleep(1200);
const probe = `(() => { const t = document.querySelector('iframe').contentWindow.twin; return { pose: [+t.pose.x.toFixed(3), +t.pose.y.toFixed(3)], robot: Object.fromEntries(Object.entries(t.robot).filter(([k, v]) => typeof v !== 'object' && typeof v !== 'function')) }; })()`;
const moving = await dash.ev(probe);
clearInterval(drive);
const pid = execSync("netstat -ano").toString().split("\n").find((l) => l.includes(HUB) && l.includes("LISTENING")).trim().split(/\s+/).pop();
execSync(`taskkill /PID ${pid} /T /F`);
const tKill = Date.now();
await sleep(700);
const a = await dash.ev(probe); await sleep(500); const b = await dash.ev(probe);
out("robot while driving (before kill)", moving);
out("0.7 s after hub killed", a);
out("robot stationary after hub death", Math.hypot(b.pose[0] - a.pose[0], b.pose[1] - a.pose[1]) < 0.002);
dash.close();
const h = spawn(`${REPO}/control/.venv/Scripts/python.exe`, ["-m", "hub", "--device", "sim", "--http-port", HUB.split(":")[1], "--host", "127.0.0.1"], { cwd: REPO, stdio: "ignore", detached: true });
h.unref();
process.exit(0);
