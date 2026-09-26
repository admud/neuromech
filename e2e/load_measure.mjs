// Dashboard (virtual robot) + phone open; sample state for 20 s while driving by sim gaze.
import { openPage, hubWatcher, sleep } from "./cdp.mjs";
const HUB = process.env.HUB || "127.0.0.1:18931";
const hub = await hubWatcher(HUB);
const dash = await openPage(`http://${HUB}/dashboard/`, 19301, { w: 1600, h: 950 });
const phone = await openPage(`http://${HUB}/phone/`, 19302, { w: 1400, h: 650 });
await sleep(8000);
console.log("START"); // cue for the CPU sampler
hub.send({ type: "arm", armed: true });
const rows = []; const f0 = await phone.ev(`window.__phone.video.frames`); const t0 = Date.now();
for (let i = 0; i < 20; i++) {
  hub.send({ type: "sim_gaze", target: i % 8 < 4 ? "up" : "down" });
  await sleep(1000); const s = hub.state; rows.push([s.phone?.fps, s.phone?.p95_ms, s.phone?.dropped, s.video?.in_fps, s.phone?.rtt_ms]);
}
const f1 = await phone.ev(`window.__phone.video.frames`);
const med = (k) => { const v = rows.map((r) => r[k]).filter((x) => x != null).sort((a, b) => a - b); return v[v.length >> 1]; };
console.log(JSON.stringify({ phone_fps: med(0), phone_p95_ms: med(1), dropped_per_s: med(2), video_in_fps: med(3), phone_rtt_ms: med(4), phone_video_fps: +((f1 - f0) / ((Date.now() - t0) / 1000)).toFixed(1) }));
hub.send({ type: "arm", armed: false }); hub.send({ type: "sim_gaze", target: null });
console.log("errors", [...dash.errors, ...phone.errors].slice(0, 4));
dash.close(); phone.close(); hub.ws.close(); process.exit(0);
