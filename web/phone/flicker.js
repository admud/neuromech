// SSVEP flicker renderer.
//
// Brightness is a function of the rAF timestamp, never of a frame counter:
// the iPhone changes refresh rate on the fly (ProMotion), and a counter
// only gives the right frequency at a fixed, known refresh rate.
//
// Per-frame work is four scissored clears in WebGL (or four fillRects in the
// 2D fallback), with no allocation: bar rects live in a preallocated typed
// array and the 2D fallback uses a precomputed table of fill styles.

export const TARGET_IDS = ["up", "down", "left", "right"];

const TWO_PI = 2 * Math.PI;

/** Luminance 0..1 at time t (seconds) for frequency f (Hz). */
export function luminance(f, t) {
  return 0.5 * (1 + Math.sin(TWO_PI * f * t));
}

/** 8-bit grey level actually shown: round(255 * L). */
export function greyLevel(f, t) {
  return Math.round(255 * luminance(f, t));
}

// Precomputed so the 2D fallback never builds a string per frame.
const GREY_STYLE = [];
for (let i = 0; i < 256; i++) GREY_STYLE.push(`rgb(${i},${i},${i})`);

export class Flicker {
  /**
   * @param {HTMLCanvasElement} canvas full-screen, behind the video
   * @param {number} bgGrey background grey level 0..255
   */
  constructor(canvas, bgGrey = 32) {
    this.canvas = canvas;
    this.freqs = new Float64Array([11, 14, 17, 20]);
    // Bars in device pixels, canvas coords (origin top-left): x, y, w, h per target.
    this.rects = new Int32Array(16);
    this.bgGrey = bgGrey;
    this.bg = bgGrey / 255;
    this.levels = new Uint8Array(4); // last drawn grey level per target (for tracing)

    const opts = { alpha: false, antialias: false, depth: false, stencil: false,
                   preserveDrawingBuffer: false, powerPreference: "high-performance" };
    this.gl = canvas.getContext("webgl2", opts) || canvas.getContext("webgl", opts);
    if (!this.gl) {
      this.ctx = canvas.getContext("2d", { alpha: false });
    }
    this.kind = this.gl ? "webgl" : "2d";
  }

  /** Set frequencies from a `config` message's targets list. */
  setTargets(targets) {
    for (const t of targets) {
      const i = TARGET_IDS.indexOf(t.id);
      if (i >= 0 && Number.isFinite(t.freq)) this.freqs[i] = t.freq;
    }
  }

  /**
   * Size the canvas backing store and set bar rects.
   * @param {number} w,h canvas size in device pixels
   * @param {object} bars {up:{x,y,w,h}, ...} in device pixels
   */
  resize(w, h, bars) {
    if (this.canvas.width !== w) this.canvas.width = w;
    if (this.canvas.height !== h) this.canvas.height = h;
    for (let i = 0; i < 4; i++) {
      const r = bars[TARGET_IDS[i]];
      this.rects[4 * i] = Math.round(r.x);
      this.rects[4 * i + 1] = Math.round(r.y);
      this.rects[4 * i + 2] = Math.round(r.w);
      this.rects[4 * i + 3] = Math.round(r.h);
    }
    if (this.gl) this.gl.viewport(0, 0, w, h);
  }

  /** Draw one frame. t = rAF timestamp in seconds. */
  draw(t) {
    const f = this.freqs, r = this.rects, lv = this.levels;
    for (let i = 0; i < 4; i++) lv[i] = Math.round(255 * 0.5 * (1 + Math.sin(TWO_PI * f[i] * t)));

    const gl = this.gl;
    if (gl) {
      const H = this.canvas.height;
      gl.disable(gl.SCISSOR_TEST);
      gl.clearColor(this.bg, this.bg, this.bg, 1);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.enable(gl.SCISSOR_TEST);
      for (let i = 0; i < 4; i++) {
        const g = lv[i] / 255;
        // WebGL scissor origin is bottom-left.
        gl.scissor(r[4 * i], H - r[4 * i + 1] - r[4 * i + 3], r[4 * i + 2], r[4 * i + 3]);
        gl.clearColor(g, g, g, 1);
        gl.clear(gl.COLOR_BUFFER_BIT);
      }
    } else {
      const c = this.ctx;
      c.fillStyle = GREY_STYLE[this.bgGrey];
      c.fillRect(0, 0, this.canvas.width, this.canvas.height);
      for (let i = 0; i < 4; i++) {
        c.fillStyle = GREY_STYLE[lv[i]];
        c.fillRect(r[4 * i], r[4 * i + 1], r[4 * i + 2], r[4 * i + 3]);
      }
    }
  }
}

/**
 * Rolling rAF-interval stats. `add()` is called every frame and allocates
 * nothing; `summary()` runs once a second.
 */
export class FrameStats {
  constructor(cap = 1024) {
    this.buf = new Float64Array(cap);
    this.scratch = new Float64Array(cap);
    this.n = 0;
  }
  add(dtMs) {
    if (this.n < this.buf.length) this.buf[this.n++] = dtMs;
  }
  /** Stats over the collected intervals, then reset. window_s is wall time covered. */
  summary(windowS) {
    const n = this.n;
    this.n = 0;
    if (n === 0) return { fps: 0, p95_ms: 0, dropped: 0, window_s: windowS };
    const s = this.scratch.subarray(0, n);
    s.set(this.buf.subarray(0, n));
    s.sort();
    const median = n % 2 ? s[(n - 1) >> 1] : 0.5 * (s[n / 2 - 1] + s[n / 2]);
    const p95 = s[Math.min(n - 1, Math.ceil(0.95 * n) - 1)];
    let dropped = 0;
    for (let i = 0; i < n; i++) if (s[i] > 1.5 * median) dropped++;
    return { fps: +(n / windowS).toFixed(1), p95_ms: +p95.toFixed(2), dropped,
             window_s: +windowS.toFixed(3) };
  }
}
