// Reconnecting WebSocket: retries every 1 s forever.
//
// Optional receive watchdog (`staleMs`): if nothing arrives for that long
// while the socket claims to be open, drop it and reconnect. On iOS a WiFi
// drop can leave a socket half-open for a long time with no close event, so
// only silence reveals it. Only use it on routes the hub talks on steadily
// (`state` at 10 Hz on /ws/phone and /ws/dashboard), not on /ws/video, which
// is legitimately silent when no robot streams.

export class Link {
  /**
   * @param {string} path e.g. "/ws/phone"
   * @param {object} h {onOpen, onClose, onMessage(data)}
   * @param {object} opts {binaryType, staleMs}
   */
  constructor(path, h, { binaryType = "arraybuffer", staleMs = 0 } = {}) {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    this.url = `${proto}//${location.host}${path}`;
    this.h = h;
    this.binaryType = binaryType;
    this.staleMs = staleMs;
    this.ws = null;
    this.open = false;
    this.lastRx = 0;
    this.stale = 0;   // count of watchdog drops, for tests
    this._connect();
    if (staleMs > 0) setInterval(() => this._watch(), 250);
  }

  _connect() {
    let ws;
    try {
      ws = new WebSocket(this.url);
    } catch (e) {
      setTimeout(() => this._connect(), 1000);
      return;
    }
    ws.binaryType = this.binaryType;
    this.ws = ws;
    // A connect that hangs is also caught by the watchdog, counted from here.
    this.lastRx = performance.now();
    ws.onopen = () => {
      this.open = true;
      this.lastRx = performance.now();
      this.h.onOpen && this.h.onOpen();
    };
    ws.onmessage = (ev) => {
      this.lastRx = performance.now();
      this.h.onMessage(ev.data);
    };
    ws.onclose = () => this._dropped(ws);
    ws.onerror = () => {}; // onclose follows
  }

  /** Socket `ws` is gone (closed, or abandoned by the watchdog). */
  _dropped(ws) {
    if (ws !== this.ws) return;  // already handled
    const was = this.open;
    this.open = false;
    this.ws = null;
    if (was && this.h.onClose) this.h.onClose();
    setTimeout(() => this._connect(), 1000);
  }

  _watch() {
    const ws = this.ws;
    if (!ws || performance.now() - this.lastRx < this.staleMs) return;
    this.stale++;
    // Don't wait for a close handshake that may never finish: detach and
    // treat it as closed now.
    ws.onopen = ws.onmessage = ws.onclose = ws.onerror = null;
    try { ws.close(); } catch (_) {}
    this._dropped(ws);
  }

  send(obj) {
    if (!this.open) return false;
    this.ws.send(JSON.stringify(obj));
    return true;
  }
}
