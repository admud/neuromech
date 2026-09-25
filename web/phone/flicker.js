// SSVEP flicker renderer: four circular targets.
//
// Brightness is a function of the rAF timestamp, never of a frame counter:
// the iPhone changes refresh rate on the fly (ProMotion), and a counter
// only gives the right frequency at a fixed, known refresh rate.
//
// Per frame: one clear to the background, then each circle drawn inside its
// own scissor box (WebGL, one tiny shader), or four arcs in the 2D fallback.
// Nothing is allocated per frame: circles live in a preallocated typed array
// and the 2D fallback uses a precomputed table of fill styles.

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

// Full-screen triangle; the fragment shader fills one anti-aliased circle.
// The scissor box keeps the work to that circle's bounding square.
const VS = `attribute vec2 p; void main() { gl_Position = vec4(p, 0.0, 1.0); }`;
const FS = `precision highp float;
uniform vec3 circle;   // centre x, centre y (GL window coords, origin bottom-left), radius; device px
uniform float grey;
uniform float bg;
void main() {
  float a = clamp(circle.z + 0.5 - distance(gl_FragCoord.xy, circle.xy), 0.0, 1.0);
  float v = mix(bg, grey, a);
  gl_FragColor = vec4(v, v, v, 1.0);
}`;

export class Flicker {
  /**
   * @param {HTMLCanvasElement} canvas full-screen, behind the video
   * @param {number} bgGrey background grey level 0..255
   */
  constructor(canvas, bgGrey = 32) {
    this.canvas = canvas;
    this.freqs = new Float64Array([11, 14, 17, 20]);
    // Circles in device pixels, canvas coords (origin top-left): cx, cy, r per target.
    this.circles = new Float64Array(12);
    this.bgGrey = bgGrey;
    this.bg = bgGrey / 255;
    this.levels = new Uint8Array(4); // last drawn grey level per target (for tracing)

    const opts = { alpha: false, antialias: false, depth: false, stencil: false,
                   preserveDrawingBuffer: false, powerPreference: "high-performance" };
    this.gl = canvas.getContext("webgl2", opts) || canvas.getContext("webgl", opts);
    if (this.gl && !this._initGL()) this.gl = null;
    if (!this.gl) this.ctx = canvas.getContext("2d", { alpha: false });
    this.kind = this.gl ? "webgl" : "2d";
  }

  _initGL() {
    const gl = this.gl;
    const sh = (type, src) => {
      const s = gl.createShader(type);
      gl.shaderSource(s, src); gl.compileShader(s);
      return gl.getShaderParameter(s, gl.COMPILE_STATUS) ? s : null;
    };
    const vs = sh(gl.VERTEX_SHADER, VS), fs = sh(gl.FRAGMENT_SHADER, FS);
    if (!vs || !fs) return false;
    const prog = gl.createProgram();
    gl.attachShader(prog, vs); gl.attachShader(prog, fs);
    gl.bindAttribLocation(prog, 0, "p");
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) return false;
    gl.useProgram(prog);
    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
    this.uCircle = gl.getUniformLocation(prog, "circle");
    this.uGrey = gl.getUniformLocation(prog, "grey");
    gl.uniform1f(gl.getUniformLocation(prog, "bg"), this.bg);
    return true;
  }

  /** Set frequencies from a `config` message's targets list. */
  setTargets(targets) {
    for (const t of targets) {
      const i = TARGET_IDS.indexOf(t.id);
      if (i >= 0 && Number.isFinite(t.freq)) this.freqs[i] = t.freq;
    }
  }

  /**
   * Size the canvas backing store and set the circles.
   * @param {number} w,h canvas size in device pixels
   * @param {object} circles {up:{cx,cy,r}, ...} in device pixels
   */
  resize(w, h, circles) {
    if (this.canvas.width !== w) this.canvas.width = w;
    if (this.canvas.height !== h) this.canvas.height = h;
    for (let i = 0; i < 4; i++) {
      const c = circles[TARGET_IDS[i]];
      this.circles[3 * i] = c.cx;
      this.circles[3 * i + 1] = c.cy;
      this.circles[3 * i + 2] = c.r;
    }
    if (this.gl) this.gl.viewport(0, 0, w, h);
  }

  /** Draw one frame. t = rAF timestamp in seconds. */
  draw(t) {
    const f = this.freqs, c = this.circles, lv = this.levels;
    for (let i = 0; i < 4; i++) lv[i] = Math.round(255 * 0.5 * (1 + Math.sin(TWO_PI * f[i] * t)));

    const gl = this.gl;
    if (gl) {
      const H = this.canvas.height;
      gl.disable(gl.SCISSOR_TEST);
      gl.clearColor(this.bg, this.bg, this.bg, 1);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.enable(gl.SCISSOR_TEST);
      for (let i = 0; i < 4; i++) {
        const cx = c[3 * i], cy = c[3 * i + 1], r = c[3 * i + 2];
        const x0 = Math.floor(cx - r - 1), y0 = Math.floor(cy - r - 1), s = Math.ceil(2 * r + 2);
        // GL window coords have their origin at the bottom-left.
        gl.scissor(x0, H - y0 - s, s, s);
        gl.uniform3f(this.uCircle, cx, H - cy, r);
        gl.uniform1f(this.uGrey, lv[i] / 255);
        gl.drawArrays(gl.TRIANGLES, 0, 3);
      }
    } else {
      const x = this.ctx;
      x.fillStyle = GREY_STYLE[this.bgGrey];
      x.fillRect(0, 0, this.canvas.width, this.canvas.height);
      for (let i = 0; i < 4; i++) {
        x.fillStyle = GREY_STYLE[lv[i]];
        x.beginPath();
        x.arc(c[3 * i], c[3 * i + 1], c[3 * i + 2], 0, TWO_PI);
        x.fill();
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
