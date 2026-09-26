// @main's direct integration test: hub --device sim + dashboard (3D sim iframe = robot) + phone page.
import { openPage, hubWatcher, sleep } from "./cdp.mjs";
const HUB = process.env.HUB || "127.0.0.1:18931";
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok }); console.log(`${ok ? "PASS" : "FAIL"}  ${name}  ${detail}`); };
const tel = (s) => s?.robot?.telemetry || {};

const hub = await hubWatcher(HUB);
const dashPage = await openPage(`http://${HUB}/dashboard/`, 19231, { w: 1600, h: 950 });
const phonePage = await openPage(`http://${HUB}/phone/`, 19232, { w: 1400, h: 650 });
await sleep(7000);

// S1 everything connected, disarmed at start
let s = hub.state;
check("S1 robot = virtual sim connected", s.robot?.connected && s.robot?.name === "virtual", JSON.stringify({ c: s.robot?.connected, n: s.robot?.name }));
check("S1 phone connected + reporting fps", s.phone?.connected && s.phone?.fps > 20, `fps=${s.phone?.fps}`);
check("S1 video from the sim reaches hub", s.video?.in_fps > 10, `in_fps=${s.video?.in_fps} viewers=${s.video?.viewers}`);
check("S1 starts disarmed", s.armed === false && s.disarm_reason === "startup", `${s.armed} ${s.disarm_reason}`);
check("S1 EEG sim ok, sim gaze available", s.eeg?.ok && s.sim !== null, JSON.stringify({ ok: s.eeg?.ok, sim: s.sim }));
const pv0 = await phonePage.ev(`window.__phone.video.frames`);
await sleep(1000);
const pv1 = await phonePage.ev(`window.__phone.video.frames`);
check("S1 phone shows the sim's FPV feed", pv1 - pv0 >= 10, `${pv1 - pv0} frames/s on phone`);

// S2 arm
hub.send({ type: "arm", armed: true });
check("S2 arm", (await hub.waitFor((st) => st.armed, 2000)) !== null);

// S3 gaze up -> forward, robot x increases
const x0 = tel(hub.state).x;
hub.send({ type: "sim_gaze", target: "up" });
const tUp = await hub.waitFor((st) => st.command?.direction === "up" && st.command?.vx > 0, 8000);
check("S3 gaze up -> command up (vx>0)", tUp !== null, `after ${tUp}s`);
await sleep(1500);
const x1 = tel(hub.state).x;
check("S3 virtual robot moves forward (+x)", x1 > x0 + 0.05, `x ${x0?.toFixed(2)} -> ${x1?.toFixed(2)}`);

// S4 gaze left -> +y
const y0 = tel(hub.state).y;
hub.send({ type: "sim_gaze", target: "left" });
const tLeft = await hub.waitFor((st) => st.command?.direction === "left" && st.command?.vy > 0, 8000);
check("S4 gaze left -> command left (vy>0)", tLeft !== null, `after ${tLeft}s`);
await sleep(1500);
const y1 = tel(hub.state).y;
check("S4 virtual robot strafes left (+y)", y1 > y0 + 0.05, `y ${y0?.toFixed(2)} -> ${y1?.toFixed(2)}`);

// S5 look away -> stop
hub.send({ type: "sim_gaze", target: null });
const tStop = await hub.waitFor((st) => st.command?.direction === null && Math.abs(tel(st).vx || 0) < 1e-6 && Math.abs(tel(st).vy || 0) < 1e-6, 8000);
check("S5 look away -> robot stops", tStop !== null, `after ${tStop}s`);
await sleep(1000);
const p0 = [tel(hub.state).x, tel(hub.state).y]; await sleep(1000); const p1 = [tel(hub.state).x, tel(hub.state).y];
check("S5 robot stays still while looking at the video", Math.hypot(p1[0] - p0[0], p1[1] - p0[1]) < 0.02, JSON.stringify([p0, p1]));

// S6 Space on the dashboard = STOP
hub.send({ type: "arm", armed: true }); await hub.waitFor((st) => st.armed, 2000);
await dashPage.key(" ", "Space", 32);
check("S6 Space on dashboard disarms", (await hub.waitFor((st) => !st.armed, 2000)) !== null, `reason=${hub.state.disarm_reason}`);

// S7 dashboard keyboard override drives the robot (arrow held ~1.2 s)
hub.send({ type: "arm", armed: true }); await hub.waitFor((st) => st.armed, 2000);
const xa = tel(hub.state).x;
await dashPage.key("ArrowDown", "ArrowDown", 40, "down");
const tOv = await hub.waitFor((st) => st.command?.source === "override" && st.command?.direction === "down", 2000);
await sleep(1200);
await dashPage.key("ArrowDown", "ArrowDown", 40, "up");
const xb = tel(hub.state).x;
check("S7 held ArrowDown -> override down, robot backs up", tOv !== null && xb < xa - 0.05, `x ${xa?.toFixed(2)} -> ${xb?.toFixed(2)}`);
check("S7 key release ends override", (await hub.waitFor((st) => st.command?.source !== "override", 1500)) !== null);

// S8 drive into a wall with override: collision flagged, robot pinned
let collided = false;
for (let i = 0; i < 60 && !collided; i++) { hub.send({ type: "override", direction: "up" }); await sleep(200); collided = !!tel(hub.state).collision; }
const xc0 = tel(hub.state).x;
for (let i = 0; i < 5; i++) { hub.send({ type: "override", direction: "up" }); await sleep(200); }
const xc1 = tel(hub.state).x;
hub.send({ type: "override", direction: null });
check("S8 wall stops the robot, collision reported", collided && Math.abs(xc1 - xc0) < 0.01, `x=${xc1?.toFixed(3)} collision=${collided}`);

// S9 closing the phone while armed -> phone_lost
phonePage.close();
check("S9 phone closed while armed -> phone_lost", (await hub.waitFor((st) => !st.armed && st.disarm_reason === "phone_lost", 4000)) !== null, `reason=${hub.state.disarm_reason}`);

// S10 closing the dashboard (the robot) while armed -> robot_lost
hub.send({ type: "arm", armed: true }); await hub.waitFor((st) => st.armed, 2000);
dashPage.close();
check("S10 virtual robot gone while armed -> robot_lost", (await hub.waitFor((st) => !st.armed && st.disarm_reason === "robot_lost", 4000)) !== null, `reason=${hub.state.disarm_reason}`);

check("no page errors", dashPage.errors.length + phonePage.errors.length === 0, [...dashPage.errors, ...phonePage.errors].slice(0, 4).join(" | "));
console.log(JSON.stringify({ pass: results.filter((r) => r.ok).length, fail: results.filter((r) => !r.ok).length, latency: { gazeUp: tUp, gazeLeft: tLeft, lookAwayStop: tStop } }));
hub.ws.close(); process.exit(0);
