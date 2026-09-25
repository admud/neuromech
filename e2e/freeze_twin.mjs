// Scenario 8 with the virtual robot: freeze (not kill) the hub while driving; the twin's watchdog must stop it.
import { openPage, hubWatcher, sleep } from "./cdp.mjs";
import { execSync, spawn } from "node:child_process";
const HUB = process.env.HUB || "127.0.0.1:18931";
import { REPO } from "./cdp.mjs";
const hub = await hubWatcher(HUB);
const dash = await openPage(`http://${HUB}/dashboard/`, 19271, { w: 1600, h: 950 });
await sleep(7000);
console.log("robot", hub.state.robot?.name, hub.state.robot?.connected);
hub.send({ type: "arm", armed: true }); await hub.waitFor((s) => s.armed, 3000);
const drive = setInterval(() => hub.send({ type: "override", direction: "up" }), 150);
await sleep(1200);
const probe = `(() => { const t = document.querySelector('iframe').contentWindow.twin; return { t: performance.now(), pose: [+t.pose.x.toFixed(3), +t.pose.y.toFixed(3)], wd: t.robot.watchdogStopped ?? t.robot.watchdog_stopped }; })()`;
const pid = execSync("netstat -ano").toString().split("\n").find((l) => l.includes(HUB) && l.includes("LISTENING")).trim().split(/\s+/).pop();
const sus = spawn(`${REPO}/control/.venv/Scripts/python.exe`, [`${REPO}/e2e/suspend.py`, pid, "6"], { stdio: ["ignore", "pipe", "inherit"] });
await new Promise((r) => sus.stdout.on("data", (d) => { if (String(d).includes("frozen")) r(); }));
clearInterval(drive);
const samples = [];
for (let i = 0; i < 30; i++) { samples.push(await dash.ev(probe)); await sleep(100); }
const t0 = samples[0].t;
let stopAt = null;
for (let i = 1; i < samples.length; i++) {
  const moved = Math.hypot(samples[i].pose[0] - samples[i - 1].pose[0], samples[i].pose[1] - samples[i - 1].pose[1]);
  if (moved < 1e-4 && stopAt === null) stopAt = ((samples[i - 1].t - t0) / 1000).toFixed(2);
}
console.log("first sample", samples[0], "last", samples.at(-1));
console.log("twin stopped moving ~", stopAt, "s after freeze confirmed");
await new Promise((r) => sus.on("exit", r));
await sleep(2500);
console.log("after resume: armed", hub.state?.armed, hub.state?.disarm_reason, "robot", hub.state?.robot?.connected);
dash.close(); hub.ws.close(); process.exit(0);
