// NeuroMech phone page: flicker targets + robot video + STOP / hold-to-arm.
//
// URL options:
//   ?demo=1     no hub: fake config/state and a generated test pattern
//   ?size=0.16  target circle diameter as a fraction of the short side
//   ?gap=0.03   gap between the circles' band and the video, as a fraction of the short side
//   ?hint=1     force the <100 fps hint (otherwise touch devices only)
//   ?trace=1    record per-frame (t, grey levels) into window.__trace for checking

import { Flicker, FrameStats, TARGET_IDS } from "./flicker.js";
import { VideoView, letterbox } from "./video.js";
import { Link } from "./net.js";
import { DemoPhoneLink, startTestPattern } from "./demo.js";

const q = new URLSearchParams(location.search);
const DEMO = q.get("demo") === "1";
const SIZE = clampNum(parseFloat(q.get("size")), 0.08, 0.35, 0.16);
const GAP = clampNum(parseFloat(q.get("gap")), 0, 0.15, 0.03);
const TRACE = q.get("trace") === "1";
const SHOW_HINT = q.get("hint") === "1" || navigator.maxTouchPoints > 0;

function clampNum(v, lo, hi, dflt) {
  return Number.isFinite(v) ? Math.min(hi, Math.max(lo, v)) : dflt;
}

const $ = (id) => document.getElementById(id);
const el = {
  flicker: $("flicker"), video: $("video"), probe: $("safe-probe"), outline: $("outline"),
  arrow: $("arrow"), armstate: $("armstate"), status: $("status"), reason: $("reason"),
  disconnected: $("disconnected"), stop: $("stop"), arm: $("arm"), hint: $("hint"),
  hintClose: $("hint-close"), start: $("start"),
};

const flicker = new Flicker(el.flicker);
const stats = new FrameStats();
let layout = null;           // CSS-pixel layout, see computeLayout()
let videoSize = [640, 480];

// ---------------------------------------------------------------- layout

/** One circle at the middle of each edge of the safe area, video in the middle.
 *  b = circle diameter = the edge band's thickness; the corners hold the buttons. */
function computeLayout(vw, vh, inset) {
  const x0 = inset.l, y0 = inset.t;
  const W = vw - inset.l - inset.r, H = vh - inset.t - inset.b;
  const s = Math.min(W, H);
  const b = Math.round(SIZE * s), g = Math.round(GAP * s);
  const c = b + g;  // corner square size
  const centre = { x: x0 + c, y: y0 + c, w: W - 2 * c, h: H - 2 * c };
  const r = b / 2, mx = x0 + W / 2, my = y0 + H / 2;
  return {
    x0, y0, W, H, b, g, c, centre,
    targets: {
      up:    { cx: mx,             cy: y0 + r,     r },
      down:  { cx: mx,             cy: y0 + H - r, r },
      left:  { cx: x0 + r,         cy: my,         r },
      right: { cx: x0 + W - r,     cy: my,         r },
    },
  };
}

function safeInsets() {
  const cs = getComputedStyle(el.probe);
  return { t: parseFloat(cs.paddingTop) || 0, r: parseFloat(cs.paddingRight) || 0,
           b: parseFloat(cs.paddingBottom) || 0, l: parseFloat(cs.paddingLeft) || 0 };
}

function place(node, r) {
  const s = node.style;
  s.left = r.x + "px"; s.top = r.y + "px"; s.width = r.w + "px"; s.height = r.h + "px";
}

function relayout() {
  const vw = window.innerWidth, vh = window.innerHeight;
  const dpr = window.devicePixelRatio || 1;
  layout = computeLayout(vw, vh, safeInsets());

  const circles = {};
  for (const id of TARGET_IDS) {
    const t = layout.targets[id];
    circles[id] = { cx: t.cx * dpr, cy: t.cy * dpr, r: t.r * dpr };
  }
  flicker.resize(Math.round(vw * dpr), Math.round(vh * dpr), circles);

  placeVideo();

  // Buttons in the bottom corners (empty by construction), thumb-sized.
  const d = Math.max(56, layout.c - 8);
  const { x0, y0, W, H, c } = layout;
  place(el.stop, { x: x0 + W - c + (c - d) / 2, y: y0 + H - c + (c - d) / 2, w: d, h: d });
  place(el.arm,  { x: x0 + (c - d) / 2,         y: y0 + H - c + (c - d) / 2, w: d, h: d });

  lastWinner = undefined;  // force outline re-place
  applyState();
}

function placeVideo() {
  const v = letterbox(videoSize[0], videoSize[1], layout.centre);
  place(el.video, v);
  const cx = v.x + v.w / 2;
  // Overlays positioned against the video rect; centred ones use translate.
  setCentred(el.armstate, cx, v.y + 6, false);
  setCentred(el.reason, cx, v.y + 36, false);
  setCentred(el.disconnected, cx, v.y + v.h / 2, true);
  setCentred(el.arrow, cx, v.y + v.h / 2, true);
  el.status.style.left = v.x + 4 + "px";
  el.status.style.top = v.y + v.h - 22 + "px";
}

function setCentred(node, x, y, vcentre) {
  node.style.left = x + "px";
  node.style.top = y + "px";
  node.style.transform = vcentre ? "translate(-50%, -50%)" : "translateX(-50%)";
}

// ---------------------------------------------------------------- frame loop

let lastTs = -1;
let winStart = -1;
let lowFpsSince = -1;
let hintDismissed = false;
let lastSummary = null;
const pageStart = performance.now();

// Optional trace: rows of [t, L_up, L_down, L_left, L_right] (grey levels).
const TRACE_N = 4096;
const trace = TRACE ? { buf: new Float64Array(TRACE_N * 5), n: 0 } : null;
if (trace) window.__trace = trace;

function frame(ts) {
  requestAnimationFrame(frame);
  flicker.draw(ts / 1000);

  if (trace && trace.n < TRACE_N) {
    const o = 5 * trace.n++;
    trace.buf[o] = ts / 1000;
    for (let i = 0; i < 4; i++) trace.buf[o + 1 + i] = flicker.levels[i];
  }

  if (lastTs >= 0) stats.add(ts - lastTs);
  lastTs = ts;
  if (winStart < 0) winStart = ts;
  if (ts - winStart >= 1000) {
    reportStats(stats.summary((ts - winStart) / 1000), ts);
    winStart = ts;
  }
}

function reportStats(s, ts) {
  lastSummary = s;
  phone.send({ type: "frame_stats", ...s, rtt_ms: rttMs });
  renderStatus();
  if (!SHOW_HINT || hintDismissed) return;
  if (s.fps < 100) {
    if (lowFpsSince < 0) lowFpsSince = ts - s.window_s * 1000;
    if (ts - lowFpsSince >= 3000 && ts - pageStart >= 3000) el.hint.hidden = false;
  } else {
    lowFpsSince = -1;
  }
}

document.addEventListener("visibilitychange", () => {
  // rAF pauses while hidden; don't count the gap as a dropped frame.
  lastTs = -1; winStart = -1; stats.n = 0;
  // Operator isn't looking at the targets any more: stop the robot.
  if (document.hidden) phone.send({ type: "arm", armed: false });
});

// ---------------------------------------------------------------- hub link

let state = null;
let rttMs = null;
let configId = null;

const phoneHandlers = {
  onOpen() {
    el.disconnected.style.display = "none";
    phone.send({ type: "hello", client: "phone", ua: navigator.userAgent,
      screen: { w: Math.round(screen.width * devicePixelRatio),
                h: Math.round(screen.height * devicePixelRatio), dpr: devicePixelRatio } });
    sendPing();
    renderStatus();
  },
  onClose() {
    el.disconnected.style.display = "block";
    state = null; rttMs = null;
    applyState();
  },
  onMessage(data) {
    let m;
    try { m = JSON.parse(data); } catch (e) { return; }
    if (!m || typeof m !== "object") return;
    if (m.type === "config" && Array.isArray(m.targets)) {
      flicker.setTargets(m.targets);
      configId = m.config_id;
      renderStatus();
    } else if (m.type === "state") {
      state = m;
      applyState();
    } else if (m.type === "pong" && typeof m.t_client === "number") {
      rttMs = Math.round(performance.now() - m.t_client * 1000);
    }
  },
};

const phone = DEMO ? new DemoPhoneLink(phoneHandlers) : new Link("/ws/phone", phoneHandlers, { staleMs: 2500 });
if (!DEMO) el.disconnected.style.display = "block";

function sendPing() { phone.send({ type: "ping", t_client: performance.now() / 1000 }); }
setInterval(sendPing, 2000);

const video = new VideoView(el.video, (w, h) => { videoSize = [w, h]; if (layout) placeVideo(); });
if (DEMO) startTestPattern((buf) => video.push(buf), 20);
else new Link("/ws/video", { onMessage(d) { if (d instanceof ArrayBuffer) video.push(d); } });

// ---------------------------------------------------------------- feedback

const ARROWS = { up: "▲", down: "▼", left: "◀", right: "▶" };
const REASONS = { startup: "Hold to arm", user: "Stopped", phone_lost: "Phone link lost",
                  eeg_stall: "EEG stalled", robot_lost: "Robot link lost" };
let lastArmed, lastWinner, lastArrow, lastReason;

function applyState() {
  const s = state;
  const armed = !!(s && s.armed);
  if (armed !== lastArmed) {
    lastArmed = armed;
    el.armstate.textContent = armed ? "ARMED" : "DISARMED";
    el.armstate.className = armed ? "armed" : "disarmed";
    el.arm.classList.toggle("hidden", armed);
    if (armed) cancelHold();
  }

  const winner = s && TARGET_IDS.includes(s.winner) ? s.winner : null;
  if (winner !== lastWinner && layout) {
    lastWinner = winner;
    if (winner) {
      // A ring in the gap around the circle, never over the flickering area.
      const t = layout.targets[winner];
      const pad = Math.max(3, Math.round(layout.g * 0.45));
      const R = t.r + pad;
      place(el.outline, { x: t.cx - R, y: t.cy - R, w: 2 * R, h: 2 * R });
      el.outline.style.borderWidth = Math.max(3, Math.round(pad * 0.7)) + "px";
      el.outline.style.display = "block";
    } else {
      el.outline.style.display = "none";
    }
  }

  const cmd = s && s.command;
  const dir = cmd && ARROWS[cmd.direction] ? cmd.direction : null;
  const arrowKey = dir ? dir + (cmd.source === "override" ? "o" : "") : null;
  if (arrowKey !== lastArrow) {
    lastArrow = arrowKey;
    if (dir) {
      el.arrow.textContent = ARROWS[dir];
      el.arrow.className = cmd.source === "override" ? "override" : "";
      el.arrow.style.display = "block";
    } else {
      el.arrow.style.display = "none";
    }
  }

  const reason = s && !s.armed && s.disarm_reason ? s.disarm_reason : null;
  if (reason !== lastReason) {
    lastReason = reason;
    el.reason.textContent = reason ? (REASONS[reason] || reason) : "";
    el.reason.style.display = reason ? "block" : "none";
  }
  renderStatus();
}

let lastStatus = "";
function renderStatus() {
  const s = state;
  const parts = [];
  parts.push(phone.open ? "hub ✓" + (rttMs != null ? " " + rttMs + "ms" : "") : "hub ✗");
  if (s && s.eeg) parts.push("EEG " + (s.eeg.ok ? "ok" : "✗" + (s.eeg.stalled_s ? " " + s.eeg.stalled_s.toFixed(1) + "s" : "")));
  else parts.push("EEG ?");
  if (s && s.robot) parts.push("robot " + (s.robot.connected ? (s.robot.name || "✓") : "✗"));
  else parts.push("robot ?");
  if (lastSummary) parts.push(lastSummary.fps.toFixed(0) + " fps p95 " + lastSummary.p95_ms.toFixed(1) + "ms");
  const txt = parts.join(" · ");
  if (txt !== lastStatus) { lastStatus = txt; el.status.textContent = txt; }
}

// ---------------------------------------------------------------- buttons

el.stop.addEventListener("pointerdown", (e) => {
  e.preventDefault();
  cancelHold();
  phone.send({ type: "arm", armed: false });
});

let holdTimer = 0;
el.arm.addEventListener("pointerdown", (e) => {
  e.preventDefault();
  try { el.arm.setPointerCapture(e.pointerId); } catch (_) {}
  cancelHold();
  // Force a style flush so the ring restarts from empty.
  void el.arm.offsetWidth;
  el.arm.classList.add("holding");
  holdTimer = setTimeout(() => {
    holdTimer = 0;
    el.arm.classList.remove("holding");
    phone.send({ type: "arm", armed: true });
  }, 1000);
});
for (const ev of ["pointerup", "pointercancel", "lostpointercapture"]) {
  el.arm.addEventListener(ev, cancelHold);
}
function cancelHold() {
  if (holdTimer) { clearTimeout(holdTimer); holdTimer = 0; }
  el.arm.classList.remove("holding");
}

el.hintClose.addEventListener("pointerdown", (e) => {
  e.preventDefault(); hintDismissed = true; el.hint.hidden = true;
});

el.start.addEventListener("pointerdown", (e) => {
  e.preventDefault();
  el.start.classList.add("gone");
  const de = document.documentElement;
  const rfs = de.requestFullscreen || de.webkitRequestFullscreen;
  if (rfs) { try { const p = rfs.call(de); if (p && p.catch) p.catch(() => {}); } catch (_) {} }
  try { screen.orientation.lock("landscape").catch(() => {}); } catch (_) {}
  try { navigator.wakeLock && navigator.wakeLock.request("screen").catch(() => {}); } catch (_) {}
});

// Block pinch/double-tap zoom and context menus on iOS.
for (const ev of ["gesturestart", "gesturechange", "dblclick", "contextmenu"]) {
  document.addEventListener(ev, (e) => e.preventDefault(), { passive: false });
}
document.addEventListener("touchmove", (e) => e.preventDefault(), { passive: false });

// ---------------------------------------------------------------- PWA

// Service workers only exist in secure contexts (HTTPS or localhost). Over
// plain http the page still installs on iPhone via Share -> Add to Home Screen.
if ("serviceWorker" in navigator && window.isSecureContext) {
  navigator.serviceWorker.register("sw.js").catch(() => {});
}
const STANDALONE = navigator.standalone === true ||
  window.matchMedia("(display-mode: standalone), (display-mode: fullscreen)").matches;
if (!STANDALONE && /iPhone|iPad/.test(navigator.userAgent)) {
  const tip = document.getElementById("install-tip");
  if (tip) tip.hidden = false;
}

// ---------------------------------------------------------------- go

window.addEventListener("resize", relayout);
window.addEventListener("orientationchange", () => setTimeout(relayout, 100));
relayout();
requestAnimationFrame(frame);

// For tests and debugging from the console.
window.__phone = { flicker, video, get stats() { return lastSummary; },
                   get layout() { return layout; }, get state() { return state; }, phone };
