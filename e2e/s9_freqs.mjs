// Scenario 9: change freqs on the dashboard form -> phone flicker follows, decoder follows, sim gaze decodes.
import { openPage, hubWatcher, sleep } from "./cdp.mjs";
const HUB = process.env.HUB || "127.0.0.1:18931";
const NEW = { up: 11.5, down: 13.5, left: 16.5, right: 19.5 };
const hub = await hubWatcher(HUB);
const dash = await openPage(`http://${HUB}/dashboard/`, 19281, { w: 1600, h: 950 });
const phone = await openPage(`http://${HUB}/phone/`, 19282, { w: 1400, h: 650 });
await sleep(7000);
const cid0 = hub.config?.config_id;
await dash.ev(`(() => { const f = document.getElementById('tune-form');
  for (const [k, v] of Object.entries(${JSON.stringify(NEW)})) { const i = f.elements['f_' + k]; i.value = v; i.dispatchEvent(new Event('input')); }
  f.requestSubmit(); return true; })()`);
await sleep(800);
console.log("config", cid0, "->", hub.config?.config_id, JSON.stringify(hub.config?.targets));
console.log("phone flicker freqs", await phone.ev(`Array.from(window.__phone.flicker.freqs)`));
// Measure the drawn flicker: record level of each bar per frame for 2 s, fit the best frequency.
const est = await phone.ev(`new Promise((res) => {
  const fl = window.__phone.flicker, rec = []; const d = fl.draw.bind(fl);
  fl.draw = (t) => { d(t); rec.push([t, ...fl.levels]); };
  setTimeout(() => { fl.draw = d; const out = [];
    for (let i = 0; i < 4; i++) { let best = [0, 0];
      for (let f = 5; f <= 30; f += 0.05) { let s = 0, c = 0;
        for (const r of rec) { const y = r[i + 1] - 127.5; s += y * Math.sin(2*Math.PI*f*r[0]); c += y * Math.cos(2*Math.PI*f*r[0]); }
        const p = s*s + c*c; if (p > best[1]) best = [f, p]; }
      out.push(+best[0].toFixed(2)); }
    res({ frames: rec.length, freqs: out }); }, 2000); })`);
console.log("measured on-screen flicker", JSON.stringify(est));
hub.send({ type: "arm", armed: true }); await hub.waitFor((s) => s.armed, 3000);
for (const g of ["right", "up"]) {
  hub.send({ type: "sim_gaze", target: g });
  const t = await hub.waitFor((s) => s.command?.direction === g, 8000);
  console.log(`gaze ${g} at new freqs -> command ${g}:`, t, "s", JSON.stringify(hub.state.command));
}
hub.send({ type: "sim_gaze", target: null });
hub.send({ type: "arm", armed: false });
console.log("warnings", JSON.stringify(hub.state.warnings), "errors", [...dash.errors, ...phone.errors]);
// restore
hub.send({ type: "set_config", freqs: { up: 11, down: 14, left: 17, right: 20 } });
await sleep(500);
dash.close(); phone.close(); hub.ws.close(); process.exit(0);
