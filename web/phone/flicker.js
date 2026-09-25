// SSVEP flicker renderer: four circular targets.
//
// Brightness is a function of the rAF timestamp, never of a frame counter:
// the iPhone changes refresh rate on the fly (ProMotion), and a counter
// only gives the right frequency at a fixed, known refresh rate.
//
// Each target is a small round element whose background colour is set once
// per frame. That is far cheaper than redrawing a full-screen canvas: on this
// laptop (4K at 1.5x, Intel GPU shared with the dashboard's 3D sim) the
// full-screen WebGL canvas made 12% of frames late, which visibly garbles the
// flicker; the four elements made 1 in 500 late under the same load.
// Nothing is allocated per frame: colours come from a precomputed table.

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

// Precomputed so the renderer never builds a string per frame.
const GREY_STYLE = [];
for (let i = 0; i < 256; i++) GREY_STYLE.push(`rgb(${i},${i},${i})`);

export class Flicker {
  /** @param {HTMLElement} container full-screen layer behind the video */
  constructor(container) {
    this.container = container;
    this.freqs = new Float64Array([11, 14, 17, 20]);
    // Circles in CSS pixels: cx, cy, r per target.
    this.circles = new Float64Array(12);
    this.levels = new Uint8Array(4); // last drawn grey level per target (for tracing)
    this.last = new Int16Array([-1, -1, -1, -1]);
    this.dots = TARGET_IDS.map((id) => {
      const d = document.createElement("div");
      d.className = "target";
      d.dataset.id = id;
      container.appendChild(d);
      return d;
    });
    this.kind = "dom";
  }

  /** Set frequencies from a `config` message's targets list. */
  setTargets(targets) {
    for (const t of targets) {
      const i = TARGET_IDS.indexOf(t.id);
      if (i >= 0 && Number.isFinite(t.freq)) this.freqs[i] = t.freq;
    }
  }

  /**
   * Place the circles.
   * @param {object} circles {up:{cx,cy,r}, ...} in CSS pixels
   */
  resize(circles) {
    for (let i = 0; i < 4; i++) {
      const c = circles[TARGET_IDS[i]], s = this.dots[i].style;
      this.circles[3 * i] = c.cx;
      this.circles[3 * i + 1] = c.cy;
      this.circles[3 * i + 2] = c.r;
      s.left = c.cx - c.r + "px";
      s.top = c.cy - c.r + "px";
      s.width = s.height = 2 * c.r + "px";
    }
  }

  /** Draw one frame. t = rAF timestamp in seconds. */
  draw(t) {
    const f = this.freqs, lv = this.levels, last = this.last;
    for (let i = 0; i < 4; i++) {
      const v = Math.round(255 * 0.5 * (1 + Math.sin(TWO_PI * f[i] * t)));
      lv[i] = v;
      if (v !== last[i]) { last[i] = v; this.dots[i].style.backgroundColor = GREY_STYLE[v]; }
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
