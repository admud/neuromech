// Video layer: one JPEG per /ws/video message, newest frame wins.
//
// At most one decode is in flight. Frames arriving meanwhile overwrite a
// single "pending" slot, so a slow decode drops stale frames instead of
// queueing them. Drawing happens when a decode finishes, outside the flicker
// rAF, so video can never stall the flicker.

export class VideoView {
  /**
   * @param {HTMLCanvasElement} canvas the centre video canvas
   * @param {(w:number,h:number)=>void} onSize called when frame size changes
   */
  constructor(canvas, onSize) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d", { alpha: false });
    this.onSize = onSize;
    this.busy = false;
    this.pending = null;
    this.frames = 0;     // frames drawn (for in-fps display)
    this.dropped = 0;    // frames replaced before decode
    this.lastFrameAt = 0;
  }

  /** Feed one JPEG (ArrayBuffer). */
  push(buf) {
    if (this.busy) {
      if (this.pending) this.dropped++;
      this.pending = buf;
      return;
    }
    this._decode(buf);
  }

  _decode(buf) {
    this.busy = true;
    createImageBitmap(new Blob([buf], { type: "image/jpeg" })).then(
      (bmp) => { this._draw(bmp); this._next(); },
      () => { this._next(); },  // corrupt frame: skip it
    );
  }

  _next() {
    this.busy = false;
    const p = this.pending;
    if (p) { this.pending = null; this._decode(p); }
  }

  _draw(bmp) {
    const c = this.canvas;
    if (c.width !== bmp.width || c.height !== bmp.height) {
      c.width = bmp.width;
      c.height = bmp.height;
      this.onSize(bmp.width, bmp.height);
    }
    // Native-size draw; CSS scales the element, so the compositor does the resize.
    this.ctx.drawImage(bmp, 0, 0);
    bmp.close();
    this.frames++;
    this.lastFrameAt = performance.now();
  }
}

/** Letterbox a w x h frame inside box {x,y,w,h}. */
export function letterbox(w, h, box) {
  const s = Math.min(box.w / w, box.h / h);
  const dw = w * s, dh = h * s;
  return { x: box.x + (box.w - dw) / 2, y: box.y + (box.h - dh) / 2, w: dw, h: dh };
}
