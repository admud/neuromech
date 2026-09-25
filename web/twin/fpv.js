// The robot's first-person camera, which IS the video feed.
//
// Per frame: render into an offscreen render target on the main renderer,
// read the pixels back asynchronously (WebGL2 PBO + fence, no GPU stall),
// and hand them to a worker (fpv_worker.js) that flips, colour-encodes and
// JPEG-encodes them. At most MAX_IN_FLIGHT frames are between render and
// send. Frames never queue: a finished frame older than one already sent,
// or one that finds the socket busy, is dropped.
//
// Why not a second WebGLRenderer + canvas.toBlob: a second GL context
// competes with the main view for this laptop's GPU, and toBlob encodes on
// the main thread; together they held the feed to 4-5 fps.
import * as THREE from "three";

// Under load the GPU readback alone waits ~100-150 ms, so the feed is
// latency-bound: overlapping frames raises the rate without making any one
// frame older. Measured on this laptop: 2 in flight ~15 fps, 3 ~19 fps.
const MAX_IN_FLIGHT = 3;

export class FpvCamera {
  /** cam = world.robot.camera; mount = model.cameraMount (robot frame);
   *  renderer = the main WebGLRenderer (shared, so there's one GL context). */
  constructor({ renderer, scene, robotGroup, cam, mount, fps = 20, quality = 0.7 }) {
    this.renderer = renderer;
    this.scene = scene;
    this.w = cam.w || 640;
    this.h = cam.h || 480;
    this.period = 1000 / fps;
    this.quality = quality;

    // three.js fov is vertical; the world file gives horizontal.
    const aspect = this.w / this.h;
    const hfov = THREE.MathUtils.degToRad(cam.hfov_deg || 70);
    const vfov = THREE.MathUtils.radToDeg(2 * Math.atan(Math.tan(hfov / 2) / aspect));
    this.camera = new THREE.PerspectiveCamera(vfov, aspect, 0.02, 30);
    // Camera looks down its -Z with +Y up. Map that to robot +x forward,
    // +z up (camera +X = robot right = -y), then pitch about camera X
    // (negative pitch_deg = look down).
    const basis = new THREE.Matrix4().makeBasis(
      new THREE.Vector3(0, -1, 0), new THREE.Vector3(0, 0, 1), new THREE.Vector3(-1, 0, 0));
    this.camera.quaternion.setFromRotationMatrix(basis);
    this.camera.rotateX(THREE.MathUtils.degToRad(mount.pitchDeg ?? cam.pitch_deg ?? 0));
    this.camera.position.set(...mount.position);
    robotGroup.add(this.camera);

    // 4x MSAA, resolved by the readback. Plain RGBA8 so the async read works.
    this.target = new THREE.WebGLRenderTarget(this.w, this.h, { samples: 4, depthBuffer: true });

    // Preview canvas (the page's picture-in-picture): shows exactly the
    // frames that were encoded, handed back by the worker as ImageBitmaps.
    this.canvas = document.createElement("canvas");
    this.canvas.width = this.w; this.canvas.height = this.h;
    this.preview = this.canvas.getContext("bitmaprenderer");

    this.lastAt = -Infinity;
    this.inFlight = 0;
    this.nextId = 0;
    this.lastSentId = -1;
    this.pool = [];                 // pixel buffers the worker handed back
    this.sent = 0; this.skipped = 0; this.encodeFailed = 0;
    this._fpsCount = 0; this._fpsT0 = performance.now(); this.fps = 0;
    this.lastBytes = 0;
    this.encodeMs = 0;              // smoothed render -> JPEG time, for diagnostics
    this._send = null;              // latest send() from tick()
    this._started = new Map();      // id -> render time

    this.worker = null;
    this.error = null;
    try {
      this.worker = new Worker(new URL("./fpv_worker.js", import.meta.url));
      this.worker.onmessage = (e) => this._onEncoded(e.data);
      this.worker.onerror = (e) => this._fail(`encoder worker: ${e.message}`);
    } catch (e) {
      this._fail(`encoder worker unavailable: ${e.message}`);
    }
  }

  _fail(msg) {
    console.error("FPV:", msg);
    this.error = msg;
    this.worker = null;
    this.inFlight = 0;
  }

  /** Call every animation frame, after the main render. `send(buf) -> bool`
   *  ships one JPEG; `canSend()` says whether the socket is idle. */
  tick(now, canSend, send) {
    this._send = send;
    if (now - this._fpsT0 >= 1000) {
      this.fps = (this._fpsCount * 1000) / (now - this._fpsT0);
      this._fpsCount = 0; this._fpsT0 = now;
    }
    if (!this.worker) return;
    // 20 fps cap. A due slot that finds the pipeline or socket busy is not
    // lost: it stays due and goes out on the first animation frame where
    // both are free.
    if (now - this.lastAt < this.period - 2) return;
    if (this.inFlight >= MAX_IN_FLIGHT || !canSend()) { this.skipped++; return; }
    this.lastAt = now - this.lastAt < this.period * 2 ? this.lastAt + this.period : now;

    const r = this.renderer;
    const prev = r.getRenderTarget();
    r.setRenderTarget(this.target);
    r.render(this.scene, this.camera);
    r.setRenderTarget(prev);

    const id = this.nextId++;
    this.inFlight++;
    this._started.set(id, now);
    const bytes = this.w * this.h * 4;
    let px = this.pool.pop();
    if (!px || px.byteLength !== bytes) px = new ArrayBuffer(bytes);
    r.readRenderTargetPixelsAsync(this.target, 0, 0, this.w, this.h, new Uint8Array(px)).then(
      () => {
        if (!this.worker) return;
        this.worker.postMessage({ id, px, w: this.w, h: this.h, quality: this.quality }, [px]);
      },
      (err) => {
        this.inFlight = Math.max(0, this.inFlight - 1);
        this._started.delete(id);
        this.encodeFailed++;
        console.warn("FPV readback:", err);
      });
  }

  _onEncoded({ id, jpeg, px, bmp }) {
    this.inFlight = Math.max(0, this.inFlight - 1);
    if (px && this.pool.length <= MAX_IN_FLIGHT) this.pool.push(px);
    const t0 = this._started.get(id);
    this._started.delete(id);
    if (!jpeg) { this.encodeFailed++; bmp?.close(); return; }
    if (t0 !== undefined) {
      const ms = performance.now() - t0;
      this.encodeMs = this.encodeMs ? 0.8 * this.encodeMs + 0.2 * ms : ms;
    }
    // Frames can finish out of order: never show or send an older one after a newer one.
    if (id < this.lastSentId) { this.skipped++; bmp?.close(); return; }
    if (bmp) this.preview.transferFromImageBitmap(bmp);
    if (!this._send || !this._send(jpeg)) { this.skipped++; return; }
    this.lastSentId = id;
    this.sent++; this._fpsCount++; this.lastBytes = jpeg.byteLength;
  }
}
