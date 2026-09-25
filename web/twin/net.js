// The two hub connections: /ws/robot (we ARE the robot) and /ws/dashboard
// (read-only, for the HUD). Both reconnect on their own.

export function hubBase() {
  const q = new URLSearchParams(location.search);
  const host = q.get("hub") || location.host;
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${host}`;
}

/** Robot side of /ws/robot. Holds the latest cmd and enforces the watchdog
 *  in `command(now)`: no cmd within ttl_ms -> zero velocity, stopped. */
export class RobotLink {
  constructor({ url, video, onStatus }) {
    this.url = url;
    this.video = video;                 // {w, h, fps} for hello
    this.onStatus = onStatus || (() => {});
    this.ws = null;
    this.connected = false;
    this.enabled = true;
    this.cmd = { vx: 0, vy: 0, seq: -1, ttl_ms: 500 };
    this.lastCmdAt = -Infinity;         // performance.now() ms
    this.cmdCount = 0;
    this.replacedStreak = 0;
    this.stoppedReason = null;          // why we stopped reconnecting, if we did
    this._retry = null;
  }

  start() {
    this.enabled = true;
    this.stoppedReason = null;
    this.replacedStreak = 0;
    this._open();
  }

  /** Give up the robot slot (another sim took over). */
  stop(reason) {
    this.enabled = false;
    this.stoppedReason = reason;
    clearTimeout(this._retry);
    if (this.ws) { try { this.ws.close(1000, reason); } catch {} }
    this.onStatus();
  }

  _open() {
    clearTimeout(this._retry);
    let ws;
    try { ws = new WebSocket(this.url); } catch { return this._scheduleRetry(); }
    ws.binaryType = "arraybuffer";
    this.ws = ws;
    let openedAt = 0;
    ws.onopen = () => {
      openedAt = performance.now();
      this.connected = true;
      ws.send(JSON.stringify({ type: "hello", client: "robot", name: "virtual", video: this.video }));
      this.onStatus();
    };
    ws.onmessage = (ev) => {
      if (typeof ev.data !== "string") return;
      let m;
      try { m = JSON.parse(ev.data); } catch { return; }
      if (m.type === "cmd") {
        this.cmd = {
          vx: clamp1(+m.vx || 0), vy: clamp1(+m.vy || 0),
          seq: m.seq, ttl_ms: m.ttl_ms > 0 ? m.ttl_ms : 500,
        };
        this.lastCmdAt = performance.now();
        this.cmdCount++;
      } else if (m.type === "ping") {
        this.sendJson({ type: "pong", t_hub: m.t_hub });
      }
    };
    ws.onclose = (ev) => {
      if (this.ws !== ws) return;
      this.connected = false;
      this.ws = null;
      // Two robots fighting over the slot: each connect closes the other.
      // If the hub keeps closing us right after we connect, or says we were
      // replaced, stop retrying instead of kicking the other robot forever.
      const short = openedAt && performance.now() - openedAt < 3000;
      const replaced = ev.code === 4001 || /replac/i.test(ev.reason || "");
      this.replacedStreak = short || replaced ? this.replacedStreak + 1 : 0;
      if (replaced || this.replacedStreak >= 3) {
        this.enabled = false;
        this.stoppedReason = "another robot took the /ws/robot slot";
      }
      this.onStatus();
      if (this.enabled) this._scheduleRetry();
    };
    ws.onerror = () => {};
  }

  _scheduleRetry() {
    clearTimeout(this._retry);
    this._retry = setTimeout(() => this.enabled && this._open(), 1000);
  }

  sendJson(obj) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(obj));
  }

  /** True if a binary frame can go out now without queueing behind another. */
  canSendFrame() {
    return !!this.ws && this.ws.readyState === WebSocket.OPEN && this.ws.bufferedAmount === 0;
  }

  sendFrame(buf) {
    if (this.canSendFrame()) { this.ws.send(buf); return true; }
    return false;
  }

  /** The velocity to apply now, after the watchdog. */
  command(now) {
    const fresh = this.connected && now - this.lastCmdAt <= this.cmd.ttl_ms;
    return fresh
      ? { vx: this.cmd.vx, vy: this.cmd.vy, watchdog: false }
      : { vx: 0, vy: 0, watchdog: true };
  }
}

/** Read-only /ws/dashboard: keeps the latest `state` and `config`. Never sends. */
export class DashLink {
  constructor({ url, onState }) {
    this.url = url;
    this.onState = onState || (() => {});
    this.state = null;
    this.config = null;
    this.connected = false;
    this.lastStateAt = 0;
  }

  start() {
    let ws;
    try { ws = new WebSocket(this.url); } catch { setTimeout(() => this.start(), 1500); return; }
    ws.onopen = () => { this.connected = true; };
    ws.onmessage = (ev) => {
      if (typeof ev.data !== "string") return;
      let m;
      try { m = JSON.parse(ev.data); } catch { return; }
      if (m.type === "state") { this.state = m; this.lastStateAt = performance.now(); this.onState(m); }
      else if (m.type === "config") this.config = m;
    };
    ws.onclose = () => { this.connected = false; this.state = null; setTimeout(() => this.start(), 1500); };
    ws.onerror = () => {};
  }
}

function clamp1(v) { return Math.max(-1, Math.min(1, v)); }
