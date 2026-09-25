// ?demo=1: a fake hub for the dashboard, with the same semantics as the
// stub engine: arm/STOP, override (expires 500 ms after the last message,
// needs armed), set_config, sim_gaze (the simulated user's gaze drives the winner).

const IDS = ["up", "down", "left", "right"];
const DIR = { up: [1, 0], down: [-1, 0], left: [0, 1], right: [0, -1] };

export class DemoDashLink {
  constructor(h) {
    this.h = h;
    this.open = true;
    this.armed = false;
    this.reason = "startup";
    this.freqs = { up: 11, down: 14, left: 17, right: 20 };
    this.params = { window_s: 3.0, margin: 0.08, dwell: 2, speed: 0.3 };
    this.configId = 1;
    this.gaze = null;
    this.override = null;
    this.overrideUntil = 0;
    this.dwellCount = 0;
    this.log = [];   // messages received, for tests
    setTimeout(() => { h.onOpen && h.onOpen(); this._config(); }, 0);
    setInterval(() => this._state(), 100);
  }

  _emit(m) { this.h.onMessage(JSON.stringify(m)); }
  _config() {
    this._emit({ type: "config", config_id: this.configId,
                 targets: IDS.map((id) => ({ id, freq: this.freqs[id] })) });
  }

  send(m) {
    this.log.push({ t: performance.now(), ...m });
    if (m.type === "arm") {
      this.armed = m.armed === true;
      this.reason = this.armed ? null : "user";
      if (!this.armed) this.override = null;
    } else if (m.type === "override") {
      this.override = IDS.includes(m.direction) ? m.direction : null;
      this.overrideUntil = this.override ? performance.now() + 500 : 0;
    } else if (m.type === "sim_gaze") {
      this.gaze = IDS.includes(m.target) ? m.target : null;
    } else if (m.type === "set_config") {
      let changed = false;
      for (const [id, f] of Object.entries(m.freqs || {})) {
        if (IDS.includes(id) && f >= 5 && f <= 40) { this.freqs[id] = f; changed = true; }
      }
      for (const k of ["window_s", "margin", "dwell", "speed"]) {
        if (typeof m[k] === "number") this.params[k] = m[k];
      }
      if (changed) { this.configId++; this._config(); }
    } else if (m.type === "ping") {
      setTimeout(() => this._emit({ type: "pong", t_client: m.t_client, t_hub: performance.now() / 1000 }), 3);
    }
    return true;
  }

  _state() {
    const now = performance.now();
    const winner = this.gaze;
    this.dwellCount = winner ? Math.min(this.params.dwell, this.dwellCount + 1) : 0;
    let dir = null, source = "none";
    if (this.armed && this.override && now < this.overrideUntil) { dir = this.override; source = "override"; }
    else if (this.armed && winner && this.dwellCount >= this.params.dwell) { dir = winner; source = "bci"; }
    const sp = this.params.speed, d = dir ? DIR[dir] : [0, 0];
    const scores = {};
    for (const id of IDS) scores[id] = +(id === winner ? 0.3 + 0.05 * Math.sin(now / 700) : 0.04 + 0.02 * Math.random()).toFixed(3);
    this._emit({
      type: "state", t_hub: now / 1000, armed: this.armed, disarm_reason: this.reason,
      winner, scores,
      command: { vx: sp * d[0], vy: sp * d[1], direction: dir, source },
      dwell: { direction: winner, count: this.dwellCount, needed: this.params.dwell },
      decode_ms: 9.5, params: { ...this.params },
      eeg: { device: "demo", port: null, fs: 250, channels: ["P7", "P8", "O1", "O2"], ok: true, stalled_s: 0,
             quality: [{ name: "O1", std_uv: 5.2, railed: false }, { name: "O2", std_uv: 6.1, railed: false },
                       { name: "P7", std_uv: 7.9, railed: false }, { name: "P8", std_uv: 250, railed: true }] },
      sim: { gaze: this.gaze },
      warnings: ["demo mode: no hub"],
      phone: { connected: true, fps: 119.8, p95_ms: 8.9, dropped: 0, rtt_ms: 12 },
      robot: { connected: true, name: "demo", rtt_ms: 6,
               telemetry: { vx: sp * d[0], vy: sp * d[1], watchdog_stopped: false, x: 0, y: 0, heading: 0 } },
      video: { in_fps: 20, viewers: 1 },
      hub: { phone_url: "http://192.168.1.23:8765/phone/", dashboard_url: "http://192.168.1.23:8765/dashboard/" },
    });
  }
}
