// Reconnecting WebSocket: retries every 1 s forever.

export class Link {
  /**
   * @param {string} path e.g. "/ws/phone"
   * @param {object} h {onOpen, onClose, onMessage(data)}
   * @param {string} binaryType
   */
  constructor(path, h, binaryType = "arraybuffer") {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    this.url = `${proto}//${location.host}${path}`;
    this.h = h;
    this.binaryType = binaryType;
    this.ws = null;
    this.open = false;
    this._connect();
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
    ws.onopen = () => { this.open = true; this.h.onOpen && this.h.onOpen(); };
    ws.onmessage = (ev) => this.h.onMessage(ev.data);
    ws.onclose = () => {
      const was = this.open;
      this.open = false;
      this.ws = null;
      if (was && this.h.onClose) this.h.onClose();
      setTimeout(() => this._connect(), 1000);
    };
    ws.onerror = () => {}; // onclose follows
  }

  send(obj) {
    if (!this.open) return false;
    this.ws.send(JSON.stringify(obj));
    return true;
  }
}
