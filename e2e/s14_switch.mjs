// Scenario 14: Virtual robot switch OFF with robot_sim running; ON while robot_sim runs; full screen keeps the sim running.
import { openPage, hubWatcher, sleep } from "./cdp.mjs";
import { spawn } from "node:child_process";
const HUB = process.env.HUB || "127.0.0.1:18931";
import { REPO } from "./cdp.mjs";
const hub = await hubWatcher(HUB);
const snap = (tag) => { const s = hub.state; console.log(tag.padEnd(44), JSON.stringify({ robot: s.robot?.name, conn: s.robot?.connected, in_fps: s.video?.in_fps })); };
const dash = await openPage(`http://${HUB}/dashboard/`, 19291, { w: 1600, h: 950 });
await sleep(7000);
snap("dashboard, switch ON (default)");
// switch OFF
await dash.ev(`(() => { const v = document.getElementById('virt'); if (v.checked) v.click(); return v.checked; })()`);
await sleep(2500);
snap("switch OFF, no robot_sim");
const rs = spawn(`${REPO}/control/.venv/Scripts/python.exe`, ["-m", "hub.sim.robot_sim", "--hub", `ws://${HUB}/ws/robot`, "--video", "test"], { cwd: REPO, stdio: ["ignore", "pipe", "pipe"] });
let rsOut = ""; rs.stdout.on("data", (d) => (rsOut += d)); rs.stderr.on("data", (d) => (rsOut += d));
await sleep(5000);
snap("switch OFF + robot_sim");
const names = []; for (let i = 0; i < 20; i++) { names.push(hub.state.robot?.name ?? "-"); await sleep(250); }
console.log("robot over 5 s:", [...new Set(names)].join(","), " iframe present:", await dash.ev(`!!document.querySelector('#simbody iframe')`));
hub.send({ type: "arm", armed: true }); await hub.waitFor((s) => s.armed, 2000);
hub.send({ type: "override", direction: "left" }); await sleep(300);
console.log("robot_sim telemetry while override left:", JSON.stringify(hub.state.robot?.telemetry));
hub.send({ type: "arm", armed: false });
// switch ON while robot_sim is still running: who wins, does it settle?
await dash.ev(`(() => { const v = document.getElementById('virt'); if (!v.checked) v.click(); return v.checked; })()`);
const seq = []; for (let i = 0; i < 40; i++) { seq.push(`${hub.state.robot?.name ?? "-"}`); await sleep(250); }
console.log("switch ON with robot_sim running, 10 s:", seq.join(" "));
console.log("twin link:", JSON.stringify(await dash.ev(`(() => { const t = document.querySelector('iframe')?.contentWindow?.twin; const l = t && (t.link || t.robotLink || t.net); return l ? { stopped: l.stoppedReason ?? null, streak: l.replacedStreak } : Object.keys(t || {}); })()`)));
rs.kill(); await sleep(3000);
snap("robot_sim killed");
// full screen with the sim ON: the robot must keep running and streaming
await dash.ev(`location.reload()`); await sleep(7000);
snap("reloaded, sim ON");
const r = await dash.ev(`(() => { const b = document.getElementById('btn-fs').getBoundingClientRect(); return [b.x + b.width/2, b.y + b.height/2]; })()`);
await dash.send("Input.dispatchMouseEvent", { type: "mousePressed", x: r[0], y: r[1], button: "left", clickCount: 1 });
await dash.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: r[0], y: r[1], button: "left", clickCount: 1 });
await sleep(1500);
console.log("fullscreen element:", await dash.ev(`document.fullscreenElement?.tagName ?? null`));
await sleep(3000);
snap("in full screen");
hub.send({ type: "arm", armed: true }); await hub.waitFor((s) => s.armed, 2000);
const x0 = hub.state.robot?.telemetry?.x; for (let i = 0; i < 6; i++) { hub.send({ type: "override", direction: "up" }); await sleep(150); }
console.log("drives in full screen: x", x0?.toFixed(3), "->", hub.state.robot?.telemetry?.x?.toFixed(3));
hub.send({ type: "arm", armed: false });
await dash.ev(`document.exitFullscreen?.().then(() => true).catch(() => false)`); await sleep(1500);
snap("after exit full screen");
console.log("errors", dash.errors.slice(0, 5));
console.log("robot_sim log:", rsOut.trim().split("\n").slice(-4).join(" | "));
dash.close(); hub.ws.close(); process.exit(0);
