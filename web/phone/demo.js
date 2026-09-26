// ?demo=1: no hub. A fake /ws/phone (config + state cycling the winner,
// handles arm and ping) and a generated 20 fps JPEG test pattern standing in
// for /ws/video, fed through the real decode path.

const IDS = ["up", "down", "left", "right"];
const DIR = { up: [1, 0], down: [-1, 0], left: [0, 1], right: [0, -1] };

export class DemoPhoneLink {
  constructor(h) {
    this.h = h;
    this.open = true;
    this.armed = false;
    this.reason = "startup";
    this.t0 = performance.now();
    this.stats = null;
    setTimeout(() => {
      h.onOpen && h.onOpen();
      this._emit({ type: "config", config_id: 1,
        targets: [{ id: "up", freq: 11 }, { id: "down", freq: 14 },
                  { id: "left", freq: 17 }, { id: "right", freq: 20 }] });
    }, 0);
    setInterval(() => this._state(), 100);
  }

  _emit(msg) { this.h.onMessage(JSON.stringify(msg)); }

  send(msg) {
    if (msg.type === "arm") {
      this.armed = !!msg.armed;
      this.reason = this.armed ? null : "user";
    } else if (msg.type === "ping") {
      setTimeout(() => this._emit({ type: "pong", t_client: msg.t_client,
                                    t_hub: performance.now() / 1000 }), 5);
    } else if (msg.type === "frame_stats") {
      this.stats = msg;
    }
    return true;
  }

  _state() {
    const t = (performance.now() - this.t0) / 1000;
    // 2 s per target, then 2 s looking at the video (no winner).
    const slot = Math.floor(t / 2) % 5;
    const winner = slot < 4 ? IDS[slot] : null;
    const scores = {};
    for (const id of IDS) scores[id] = id === winner ? 0.3 : 0.05;
    const moving = this.armed && winner;
    const d = moving ? DIR[winner] : [0, 0];
    const s = this.stats || {};
    this._emit({
      type: "state", t_hub: t, armed: this.armed, disarm_reason: this.reason,
      winner, scores,
      command: { vx: 0.3 * d[0], vy: 0.3 * d[1], direction: moving ? winner : null,
                 source: moving ? "bci" : "none" },
      eeg: { device: "demo", ok: true, stalled_s: 0 },
      phone: { connected: true, fps: s.fps, p95_ms: s.p95_ms, dropped: s.dropped },
      robot: { connected: true, name: "demo" },
      video: { in_fps: 20, viewers: 1 },
    });
  }
}

/** Calls onFrame(ArrayBuffer) with a 640x480 JPEG test pattern at `fps`. */
export function startTestPattern(onFrame, fps = 20) {
  const c = document.createElement("canvas");
  c.width = 640; c.height = 480;
  const g = c.getContext("2d");
  let n = 0, busy = false;
  setInterval(() => {
    if (busy) return;
    busy = true;
    n++;
    const t = performance.now() / 1000;
    g.fillStyle = "#2a3a4a"; g.fillRect(0, 0, 640, 480);
    // grid scrolling left, like driving forward past posts
    g.strokeStyle = "#6a8aaa"; g.lineWidth = 2;
    const off = (t * 80) % 80;
    for (let x = -off; x < 640; x += 80) { g.beginPath(); g.moveTo(x, 0); g.lineTo(x, 480); g.stroke(); }
    for (let y = 0; y < 480; y += 80) { g.beginPath(); g.moveTo(0, y); g.lineTo(640, y); g.stroke(); }
    g.fillStyle = "#e0c040";
    g.beginPath(); g.arc(320 + 200 * Math.cos(t), 240 + 150 * Math.sin(t), 30, 0, 2 * Math.PI); g.fill();
    g.fillStyle = "#fff"; g.font = "28px sans-serif";
    g.fillText(`DEMO test pattern  frame ${n}  t=${t.toFixed(2)}`, 20, 40);
    c.toBlob((b) => {
      busy = false;
      if (b) b.arrayBuffer().then(onFrame);
    }, "image/jpeg", 0.7);
  }, 1000 / fps);
}
