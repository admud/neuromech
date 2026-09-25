// NeuroMech operator dashboard.
//
// ?demo=1  no hub: a fake engine answers arm/override/set_config/sim_gaze
//          and a generated test pattern stands in for /ws/video.
//
// Safety: Esc anywhere and Space outside text fields send STOP, from this
// page and from the embedded sim iframe (which forwards keys with
// postMessage). Driving keys are tracked per source; keys forwarded by the
// iframe expire if not refreshed by key-repeat, so a keyup lost when the
// iframe loses focus can never leave the robot driving.

import { Link } from "../phone/net.js";
import { VideoView } from "../phone/video.js";
import { startTestPattern } from "../phone/demo.js";
import { DemoDashLink } from "./demo.js";

const q = new URLSearchParams(location.search);
const DEMO = q.get("demo") === "1";
const IDS = ["up", "down", "left", "right"];
const ARROW = { up: "▲", down: "▼", left: "◀", right: "▶" };
const REASONS = { startup: "startup: press ARM", user: "stopped by user",
  phone_lost: "phone disconnected", eeg_stall: "EEG stalled", robot_lost: "robot disconnected" };

const $ = (id) => document.getElementById(id);

// ------------------------------------------------------------------ link

let state = null;
let config = null;
let rttMs = null;

const handlers = {
  onOpen() {
    $("disconnected").style.display = "none";
    $("hub-dot").classList.add("ok");
    ping();
  },
  onClose() {
    $("disconnected").style.display = "block";
    $("hub-dot").classList.remove("ok");
    state = null; rttMs = null;
    render();
  },
  onMessage(data) {
    let m;
    try { m = JSON.parse(data); } catch (e) { return; }
    if (!m || typeof m !== "object") return;
    if (m.type === "state") { state = m; render(); }
    else if (m.type === "config") { config = m; onConfig(); }
    else if (m.type === "pong" && typeof m.t_client === "number") {
      rttMs = Math.round(performance.now() - m.t_client * 1000);
      $("hub-rtt").textContent = rttMs + " ms";
    }
  },
};
const hub = DEMO ? new DemoDashLink(handlers) : new Link("/ws/dashboard", handlers, { staleMs: 2500 });
if (!DEMO) $("disconnected").style.display = "block";
const send = (m) => hub.send(m);

function ping() { send({ type: "ping", t_client: performance.now() / 1000 }); }
setInterval(ping, 2000);

// ------------------------------------------------------------------ safety

function stop() {
  releaseAll();
  send({ type: "arm", armed: false });
  flash($("btn-stop"));
}
function arm() { send({ type: "arm", armed: true }); }

$("btn-stop").addEventListener("click", (e) => { stop(); e.currentTarget.blur(); });
$("btn-arm").addEventListener("click", (e) => { arm(); e.currentTarget.blur(); });

function flash(node) {
  node.style.outline = "4px solid #ff0";
  setTimeout(() => { node.style.outline = ""; }, 150);
}

// ------------------------------------------------------------------ keys + override

const KEY_DIR = { arrowup: "up", w: "up", arrowdown: "down", s: "down",
                  arrowleft: "left", a: "left", arrowright: "right", d: "right" };
const GAZE_KEY = { "1": "up", "2": "down", "3": "left", "4": "right", "0": null };
const TWIN_HOLD_MS = 800;   // key-repeat refreshes this well inside the limit

// Active holds, oldest first; the newest one decides the direction.
const holds = [];  // {id, dir, expires}
let sentDir = null;

function hold(id, dir, expires = Infinity) {
  const i = holds.findIndex((h) => h.id === id);
  if (i >= 0) { holds[i].expires = expires; return; }
  holds.push({ id, dir, expires });
  pushOverride();
}
function release(id) {
  const i = holds.findIndex((h) => h.id === id);
  if (i >= 0) { holds.splice(i, 1); pushOverride(); }
}
function releaseAll() {
  holds.length = 0;
  pushOverride();
}
function currentDir() {
  const now = performance.now();
  for (let i = holds.length - 1; i >= 0; i--) if (holds[i].expires < now) holds.splice(i, 1);
  return holds.length ? holds[holds.length - 1].dir : null;
}
/** Send the override now if it changed; the 200 ms tick keeps it alive. */
function pushOverride() {
  const dir = currentDir();
  if (dir !== sentDir || dir) send({ type: "override", direction: dir });
  sentDir = dir;
  renderOverride();
}
setInterval(() => {
  const dir = currentDir();
  if (dir) send({ type: "override", direction: dir });
  else if (sentDir) send({ type: "override", direction: null });
  sentDir = dir;
  renderOverride();
}, 200);

function isTyping(target) {
  if (!target || !target.tagName) return false;
  const t = target.tagName;
  return t === "INPUT" || t === "TEXTAREA" || t === "SELECT" || target.isContentEditable;
}

/** Shared by local keyboard events and keys forwarded from the twin iframe. */
function onKey(type, key, { twin = false, typing = false, repeat = false } = {}) {
  if (key === "Escape") { if (type === "keydown") stop(); return true; }
  if (key === " " || key === "Spacebar") {
    if (typing) return false;
    if (type === "keydown") stop();
    return true;
  }
  if (typing) return false;
  const k = key.toLowerCase();
  const dir = KEY_DIR[k];
  if (dir) {
    const id = (twin ? "t:" : "k:") + k;
    if (type === "keydown") hold(id, dir, twin ? performance.now() + TWIN_HOLD_MS : Infinity);
    else release(id);
    return true;
  }
  if (k in GAZE_KEY && type === "keydown" && !repeat) {
    if (state && state.sim) send({ type: "sim_gaze", target: GAZE_KEY[k] });
    return true;
  }
  return false;
}

window.addEventListener("keydown", (e) => {
  if (onKey("keydown", e.key, { typing: isTyping(e.target), repeat: e.repeat })) e.preventDefault();
});
window.addEventListener("keyup", (e) => {
  // Always process releases, even from inside a field, so nothing sticks.
  const k = e.key.toLowerCase();
  if (KEY_DIR[k]) { release("k:" + k); return; }
  if (onKey("keyup", e.key, { typing: isTyping(e.target) })) e.preventDefault();
});
// Our own keys can't be released while we lack focus (e.g. the iframe took it).
window.addEventListener("blur", () => {
  for (const h of holds.slice()) if (h.id.startsWith("k:") || h.id === "pad") release(h.id);
});
// Keys forwarded by the sim iframe (protocol.md, "sim iframe -> dashboard").
window.addEventListener("message", (e) => {
  const m = e.data;
  if (!m || m.type !== "twin-key" || typeof m.key !== "string") return;
  if (m.event !== "keydown" && m.event !== "keyup") return;
  onKey(m.event, m.key, { twin: true });
});

// On-screen D-pad (mouse / touch).
for (const b of document.querySelectorAll("#dpad button")) {
  const dir = b.dataset.dir;
  b.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    try { b.setPointerCapture(e.pointerId); } catch (_) {}
    release("pad");
    hold("pad", dir);
  });
  for (const ev of ["pointerup", "pointercancel", "lostpointercapture"]) {
    b.addEventListener(ev, () => release("pad"));
  }
}

let lastOvr = "";
function renderOverride() {
  const dir = sentDir;
  const txt = dir ? dir : "none";
  if (txt !== lastOvr) {
    lastOvr = txt;
    $("ovr").textContent = txt;
    for (const b of document.querySelectorAll("#dpad button")) b.classList.toggle("on", b.dataset.dir === dir);
  }
  const armed = state && state.armed;
  $("ovr-note").textContent = dir && !armed ? "not armed: override ignored" : "";
}

// ------------------------------------------------------------------ sim gaze

for (const b of document.querySelectorAll("#gaze-btns button")) {
  b.addEventListener("click", () => send({ type: "sim_gaze", target: b.dataset.gaze || null }));
}

// ------------------------------------------------------------------ tuning

const form = $("tune-form");
const FIELDS = ["f_up", "f_down", "f_left", "f_right", "window_s", "margin", "dwell", "speed"];
const inputs = Object.fromEntries(FIELDS.map((n) => [n, form.elements[n]]));
let pendingTune = null;   // {sent: {...}, at}

/** The hub's currently accepted values, keyed like the form fields. */
function hubValues() {
  const v = {};
  const freqs = {};
  if (config && Array.isArray(config.targets)) for (const t of config.targets) freqs[t.id] = t.freq;
  for (const id of IDS) v["f_" + id] = freqs[id];
  const p = (state && state.params) || {};
  for (const k of ["window_s", "margin", "dwell", "speed"]) v[k] = p[k];
  return v;
}

for (const n of FIELDS) {
  inputs[n].addEventListener("input", () => inputs[n].classList.add("dirty"));
}

function syncForm() {
  const v = hubValues();
  for (const n of FIELDS) {
    const inp = inputs[n];
    if (inp.classList.contains("dirty") || document.activeElement === inp) continue;
    if (v[n] != null && inp.value !== String(v[n])) inp.value = v[n];
  }
  if (pendingTune) checkTune(v);
}

function same(a, b) { return a != null && b != null && Math.abs(Number(a) - Number(b)) < 1e-6; }

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const v = hubValues();
  const msg = { type: "set_config" };
  const sent = {};
  const freqs = {};
  for (const n of FIELDS) {
    const raw = inputs[n].value.trim();
    inputs[n].classList.remove("dirty");
    if (raw === "") continue;
    const num = Number(raw);
    if (!Number.isFinite(num) || same(num, v[n])) continue;
    sent[n] = num;
    if (n.startsWith("f_")) freqs[n.slice(2)] = num;
    else msg[n] = n === "dwell" ? Math.round(num) : num;
  }
  if (Object.keys(freqs).length) msg.freqs = freqs;
  if (!Object.keys(sent).length) { tuneStatus("nothing changed", ""); return; }
  send(msg);
  pendingTune = { sent, at: performance.now() };
  tuneStatus("sent " + Object.keys(sent).join(", ") + "…", "");
});

$("tune-reset").addEventListener("click", () => {
  for (const n of FIELDS) inputs[n].classList.remove("dirty");
  pendingTune = null;
  tuneStatus("", "");
  syncForm();
});

function checkTune(v) {
  const { sent, at } = pendingTune;
  const ok = [], bad = [];
  for (const n in sent) (same(sent[n], v[n]) ? ok : bad).push(n);
  if (!bad.length) {
    tuneStatus("applied: " + ok.join(", "), "good");
    pendingTune = null;
  } else if (performance.now() - at > 1500) {
    tuneStatus("not accepted: " + bad.map((n) => `${n} (hub keeps ${v[n]})`).join(", "), "bad");
    pendingTune = null;
  }
}

function tuneStatus(txt, cls) {
  const el = $("tune-status");
  el.textContent = txt;
  el.className = cls;
}

function onConfig() {
  buildScores();
  syncForm();
}

// ------------------------------------------------------------------ decoder panel

const scoreRows = {};
function buildScores() {
  const box = $("scores");
  if (!Object.keys(scoreRows).length) {
    for (const id of IDS) {
      const row = document.createElement("div");
      row.className = "score";
      row.innerHTML = `<span class="name"></span><div class="track"><div class="fill"></div></div><span class="val"></span>`;
      box.appendChild(row);
      scoreRows[id] = { row, name: row.children[0], fill: row.children[1].firstChild, val: row.children[2] };
    }
  }
  const freqs = {};
  if (config && config.targets) for (const t of config.targets) freqs[t.id] = t.freq;
  for (const id of IDS) {
    scoreRows[id].name.textContent = `${ARROW[id]} ${id}` + (freqs[id] != null ? ` ${freqs[id]}` : "");
  }
}
buildScores();

// ------------------------------------------------------------------ render state

function fmt(x, d = 2) { return typeof x === "number" && Number.isFinite(x) ? x.toFixed(d) : "–"; }
function yes(b) { return b ? '<span class="good">✓</span>' : '<span class="bad">✗</span>'; }
function esc(s) { return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

function render() {
  const s = state;
  // Safety header.
  const armed = !!(s && s.armed);
  $("armbox").className = armed ? "armed" : "disarmed";
  $("armword").textContent = s ? (armed ? "ARMED" : "DISARMED") : "NO HUB";
  $("armreason").textContent = s && !armed ? (REASONS[s.disarm_reason] || s.disarm_reason || "") : "";
  $("btn-arm").disabled = armed || !s;

  const c = s && s.command;
  $("cmd-dir").textContent = c && c.direction ? ARROW[c.direction] + " " + c.direction : "·";
  $("cmd-detail").textContent = c ? `vx ${fmt(c.vx)} vy ${fmt(c.vy)} · ${c.source || "none"}` : "";

  if (s && s.hub && s.hub.phone_url) $("phone-url").textContent = s.hub.phone_url;

  // Decoder.
  const scores = (s && s.scores) || {};
  let max = 0.5;
  for (const id of IDS) if (scores[id] > max) max = scores[id];
  for (const id of IDS) {
    const r = scoreRows[id];
    const v = scores[id];
    r.fill.style.width = (typeof v === "number" ? Math.max(0, v) / max * 100 : 0) + "%";
    r.val.textContent = fmt(v, 3);
    r.row.classList.toggle("win", !!s && s.winner === id);
  }
  const dw = s && s.dwell;
  $("dwell-dir").textContent = dw && dw.direction ? dw.direction : "–";
  const pips = $("dwell-pips");
  const need = dw && dw.needed > 0 ? Math.min(dw.needed, 20) : 0;
  if (pips.childElementCount !== need) {
    pips.textContent = "";
    for (let i = 0; i < need; i++) { const p = document.createElement("span"); p.className = "pip"; pips.appendChild(p); }
  }
  for (let i = 0; i < need; i++) pips.children[i].classList.toggle("on", i < dw.count);
  $("decode-ms").textContent = s && s.decode_ms != null ? `decode ${fmt(s.decode_ms, 1)} ms` : "";
  const w = (s && s.warnings) || [];
  $("warnings").innerHTML = w.map((x) => `<div>⚠ ${esc(x)}</div>`).join("");

  // Sim gaze.
  const sim = s && s.sim;
  $("gaze").hidden = !sim;
  if (sim) for (const b of document.querySelectorAll("#gaze-btns button")) {
    b.classList.toggle("on", (b.dataset.gaze || null) === (sim.gaze || null));
  }

  renderLinks(s);
  renderOverride();
  syncForm();
}

function renderLinks(s) {
  const rows = [];
  const e = s && s.eeg;
  if (e) {
    let t = `${yes(e.ok)} ${esc(e.device || "?")}${e.port ? " " + esc(e.port) : ""} · ${e.fs || "?"} Hz · ${esc((e.channels || []).join(" "))}`;
    if (e.stalled_s > 0.3) t += ` · <span class="bad">stalled ${fmt(e.stalled_s, 1)} s</span>`;
    if (Array.isArray(e.quality) && e.quality.length) {
      t += '<div class="q">' + e.quality.map((c) =>
        `<span class="${c.railed ? "bad" : ""}">${esc(c.name)} ${fmt(c.std_uv, 1)}µV${c.railed ? " RAILED" : ""}</span>`).join(" · ") + "</div>";
    }
    rows.push(["EEG", t]);
  } else rows.push(["EEG", "–"]);

  const p = s && s.phone;
  if (p) {
    const fpsCls = typeof p.fps === "number" && p.fps < 100 ? "bad" : "good";
    rows.push(["Phone", p.connected
      ? `${yes(true)} <span class="${fpsCls}">${fmt(p.fps, 1)} fps</span> · p95 ${fmt(p.p95_ms, 1)} ms · dropped ${p.dropped ?? "–"} · rtt ${p.rtt_ms ?? "–"} ms`
      : yes(false) + " not connected"]);
  } else rows.push(["Phone", "–"]);

  const r = s && s.robot;
  if (r) {
    let t = r.connected ? `${yes(true)} ${esc(r.name || "?")} · rtt ${r.rtt_ms ?? "–"} ms` : yes(false) + " not connected";
    const tel = r.telemetry;
    if (r.connected && tel) {
      t += ` · v ${fmt(tel.vx)}, ${fmt(tel.vy)}`;
      if (tel.watchdog_stopped) t += ' · <span class="bad">WATCHDOG STOP</span>';
      if (tel.collision) t += ' · <span class="warn">collision</span>';
      if (typeof tel.x === "number") t += `<div class="q">pose x ${fmt(tel.x)} y ${fmt(tel.y)} hdg ${fmt((tel.heading || 0) * 180 / Math.PI, 0)}°</div>`;
      if (tel.battery_v != null) t += ` · ${fmt(tel.battery_v, 2)} V`;
    }
    rows.push(["Robot", t]);
  } else rows.push(["Robot", "–"]);

  const v = s && s.video;
  rows.push(["Video", v ? `in ${fmt(v.in_fps, 1)} fps · ${v.viewers ?? "–"} viewers` : "–"]);

  const html = rows.map(([k, t]) => `<div class="k">${k}</div><div>${t}</div>`).join("");
  const box = $("links-body");
  if (box.innerHTML !== html) box.innerHTML = html;
  $("vid-info").textContent = v ? `${fmt(v.in_fps, 1)} fps` : "";
}

// ------------------------------------------------------------------ video + sim panel

const video = new VideoView($("video"), () => {});
if (DEMO) startTestPattern((buf) => video.push(buf), 20);
else new Link("/ws/video", { onMessage(d) { if (d instanceof ArrayBuffer) video.push(d); } });

const VIRT_KEY = "neuromech.virtualRobot";
const virt = $("virt");
virt.checked = localStorage.getItem(VIRT_KEY) !== "0";
let iframe = null;

function applyVirt() {
  localStorage.setItem(VIRT_KEY, virt.checked ? "1" : "0");
  const body = $("simbody");
  const canvas = $("video");
  if (virt.checked) {
    // The iframe IS the virtual robot; keep it visible or it freezes.
    if (!iframe) {
      iframe = document.createElement("iframe");
      iframe.src = "/twin/?embed=1";
      iframe.title = "3D virtual sim";
      iframe.allow = "fullscreen";
      body.appendChild(iframe);
    }
    $("vidslot").appendChild(canvas);
    $("vidpanel").hidden = false;
  } else {
    if (iframe) { iframe.remove(); iframe = null; }
    body.appendChild(canvas);          // video preview takes the sim's place
    $("vidpanel").hidden = true;
  }
  $("btn-fs").disabled = !virt.checked;
}
virt.addEventListener("change", () => { applyVirt(); virt.blur(); });
applyVirt();

$("btn-fs").addEventListener("click", (e) => {
  e.currentTarget.blur();
  if (!iframe) return;
  const f = iframe.requestFullscreen || iframe.webkitRequestFullscreen;
  if (f) { const p = f.call(iframe); if (p && p.catch) p.catch(() => {}); }
});

render();

window.__dash = { get state() { return state; }, get config() { return config; }, hub, video,
                  get holds() { return holds; }, get sentDir() { return sentDir; } };
