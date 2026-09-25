// The robot's first-person camera, which IS the video feed. It has its own
// small WebGLRenderer (same scene) so a frame can be encoded straight from
// its canvas without touching the main view. Frames never queue: if the
// last encode or send hasn't finished, the frame is skipped.
import * as THREE from "three";

export class FpvCamera {
  /** cam = world.robot.camera; mount = model.cameraMount (robot frame). */
  constructor({ scene, robotGroup, cam, mount, fps = 20, quality = 0.7 }) {
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

    this.canvas = document.createElement("canvas");
    this.canvas.width = this.w; this.canvas.height = this.h;
    this.renderer = new THREE.WebGLRenderer({
      canvas: this.canvas, antialias: true, preserveDrawingBuffer: true, powerPreference: "high-performance",
    });
    this.renderer.setPixelRatio(1);
    this.renderer.setSize(this.w, this.h, false);
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFShadowMap;

    this.lastAt = -Infinity;
    this.inFlight = false;
    this.sent = 0; this.skipped = 0;
    this._fpsCount = 0; this._fpsT0 = performance.now(); this.fps = 0;
    this.lastBytes = 0;
  }

  /** Call every animation frame. `send(buf) -> bool` ships one JPEG;
   *  `canSend()` says whether the socket is idle. */
  tick(now, canSend, send) {
    if (now - this._fpsT0 >= 1000) {
      this.fps = (this._fpsCount * 1000) / (now - this._fpsT0);
      this._fpsCount = 0; this._fpsT0 = now;
    }
    if (now - this.lastAt < this.period - 2) return;
    // Keep the cadence even when late, but never burst to catch up.
    this.lastAt = now - this.lastAt < this.period * 2 ? this.lastAt + this.period : now;
    this.renderer.render(this.scene, this.camera);   // keeps the preview live
    if (this.inFlight || !canSend()) { this.skipped++; return; }
    this.inFlight = true;
    this.canvas.toBlob(async (blob) => {
      try {
        if (!blob) return;
        const buf = await blob.arrayBuffer();
        if (send(buf)) { this.sent++; this._fpsCount++; this.lastBytes = buf.byteLength; }
        else this.skipped++;
      } finally {
        this.inFlight = false;
      }
    }, "image/jpeg", this.quality);
  }
}
