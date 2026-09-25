// Brain-control state, drawn two ways: in 3D on the robot (armed ring,
// direction arrow filling with dwell) and as a small HTML overlay (score
// bars, links, fps). Both read the hub's `state` message.
import * as THREE from "three";

const TARGETS = ["up", "down", "left", "right"];
const ARROW_YAW = { up: 0, left: Math.PI / 2, down: Math.PI, right: -Math.PI / 2 };
const ARROWS = { up: "▲", down: "▼", left: "◀", right: "▶" };
const COLOR = {
  armed: 0x2ecc71, disarmed: 0xe0463a, stale: 0x7f8790,
  bci: 0x2ecc71, override: 0x36a3ff, dwell: 0xffb020,
};

/** 3D markers that follow the robot. Add `.object` as a child of the robot pose group. */
export class RobotHud3D {
  constructor(dims) {
    this.object = new THREE.Group();
    const r = dims.footprintRadius;

    this.ringMat = new THREE.MeshBasicMaterial({ color: COLOR.stale, transparent: true, opacity: 0.85, depthWrite: false });
    const ring = new THREE.Mesh(new THREE.RingGeometry(r + 0.02, r + 0.055, 64), this.ringMat);
    ring.position.z = 0.004;
    ring.renderOrder = 1;
    this.object.add(ring);

    // Arrow pointing +x, flat, floating above the robot.
    this.arrow = new THREE.Group();
    this.arrow.position.z = dims.height + 0.08;
    this.object.add(this.arrow);
    const L = Math.max(0.22, r * 1.8), shaftEnd = L * 0.62, sw = L * 0.16;
    this.shaftLen = shaftEnd - 0.02;
    const head = new THREE.Shape();
    head.moveTo(shaftEnd, -sw * 1.6); head.lineTo(L, 0); head.lineTo(shaftEnd, sw * 1.6); head.closePath();
    const headGeo = new THREE.ShapeGeometry(head);
    const shaftGeo = new THREE.PlaneGeometry(1, sw);
    shaftGeo.translate(0.5, 0, 0);        // grows from x = 0 when scaled

    const ghostMat = new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.22, depthWrite: false, side: THREE.DoubleSide });
    this.fillMat = new THREE.MeshBasicMaterial({ color: COLOR.dwell, side: THREE.DoubleSide, transparent: true, opacity: 0.95 });
    const ghostShaft = new THREE.Mesh(shaftGeo, ghostMat);
    ghostShaft.position.x = 0.02; ghostShaft.scale.x = this.shaftLen;
    this.arrow.add(ghostShaft, new THREE.Mesh(headGeo, ghostMat));
    this.fillShaft = new THREE.Mesh(shaftGeo, this.fillMat);
    this.fillShaft.position.set(0.02, 0, 0.001);
    this.fillHead = new THREE.Mesh(headGeo, this.fillMat);
    this.fillHead.position.z = 0.001;
    this.arrow.add(this.fillShaft, this.fillHead);
    for (const m of this.arrow.children) m.renderOrder = 2;
    this.arrow.visible = false;
  }

  /** state: latest hub state or null (not connected). */
  update(state) {
    if (!state) {
      this.ringMat.color.setHex(COLOR.stale);
      this.arrow.visible = false;
      return;
    }
    this.ringMat.color.setHex(state.armed ? COLOR.armed : COLOR.disarmed);

    const cmd = state.command || {};
    const dwell = state.dwell || {};
    let dir = null, p = 0, color = COLOR.dwell;
    if (cmd.direction && cmd.direction !== "none" && ARROW_YAW[cmd.direction] !== undefined) {
      dir = cmd.direction; p = 1;
      color = cmd.source === "override" ? COLOR.override : COLOR.bci;
      if (!state.armed) color = COLOR.stale;
    } else if (dwell.direction && ARROW_YAW[dwell.direction] !== undefined) {
      dir = dwell.direction;
      p = dwell.needed > 0 ? Math.min(1, (dwell.count || 0) / dwell.needed) : 0;
    }
    this.arrow.visible = !!dir;
    if (!dir) return;
    this.arrow.rotation.z = ARROW_YAW[dir];
    this.fillMat.color.setHex(color);
    this.fillShaft.visible = p > 0;
    this.fillShaft.scale.x = Math.max(1e-3, this.shaftLen * p);
    this.fillHead.visible = p >= 1;
  }
}

/** HTML overlay. `el` is the #hud container from index.html. */
export class HudOverlay {
  constructor(el) {
    this.el = el;
    this.$ = (id) => el.querySelector(`[data-k="${id}"]`);
    const bars = this.$("bars");
    this.bars = {};
    for (const t of TARGETS) {
      const row = document.createElement("div");
      row.className = "bar-row";
      row.innerHTML = `<span class="bar-lbl">${ARROWS[t]}</span><span class="bar"><span class="bar-fill"></span></span><span class="bar-val">–</span>`;
      bars.appendChild(row);
      this.bars[t] = { row, fill: row.querySelector(".bar-fill"), val: row.querySelector(".bar-val") };
    }
  }

  update({ state, dashConnected, robot, motion, fpv, camMode, paused }) {
    const s = state;
    const armed = this.$("armed");
    if (!s) {
      armed.textContent = dashConnected ? "NO STATE" : "HUB ?";
      armed.className = "badge stale";
      this.$("reason").textContent = "";
    } else {
      armed.textContent = s.armed ? "ARMED" : "DISARMED";
      armed.className = "badge " + (s.armed ? "armed" : "disarmed");
      this.$("reason").textContent = !s.armed && s.disarm_reason ? s.disarm_reason : "";
    }

    const cmd = s?.command;
    this.$("cmd").textContent = cmd && cmd.direction && cmd.direction !== "none"
      ? `${ARROWS[cmd.direction] || ""} ${cmd.direction} (${cmd.source})` : "stop";
    const dw = s?.dwell;
    this.$("dwell").textContent = dw && dw.direction ? `${dw.direction} ${dw.count}/${dw.needed}` : "–";

    const scores = s?.scores || {};
    const vals = TARGETS.map((t) => +scores[t] || 0);
    const top = Math.max(0.5, ...vals);
    for (const t of TARGETS) {
      const b = this.bars[t], v = +scores[t] || 0;
      b.fill.style.width = `${Math.min(100, (100 * v) / top)}%`;
      b.val.textContent = scores[t] == null ? "–" : v.toFixed(2);
      b.row.classList.toggle("win", s?.winner === t);
    }

    const ph = s?.phone;
    this.$("phone").textContent = ph ? (ph.connected ? `${(ph.fps ?? 0).toFixed(0)} fps` : "off") : "–";
    this.$("phone").className = ph?.connected ? (ph.fps >= 100 ? "ok" : "warn") : "bad";
    const eeg = s?.eeg;
    this.$("eeg").textContent = eeg ? `${eeg.device}${eeg.ok ? "" : " STALL"}` : "–";
    this.$("eeg").className = eeg ? (eeg.ok ? "ok" : "bad") : "";
    this.$("hub").className = dashConnected ? "ok" : "bad";
    this.$("hub").textContent = dashConnected ? "ok" : "off";
    this.$("robot").className = robot.connected ? "ok" : "bad";
    this.$("robot").textContent = robot.connected ? "virtual" : robot.stoppedReason ? "released" : "off";

    this.$("motion").textContent =
      `v ${motion.vx.toFixed(2)}, ${motion.vy.toFixed(2)}` +
      (motion.watchdog ? " · watchdog" : "") + (motion.collision ? " · bump" : "");
    this.$("motion").className = motion.collision ? "warn" : motion.watchdog ? "dim" : "";
    document.getElementById("fpvstat").textContent = `${fpv.fps.toFixed(0)} fps · ${(fpv.lastBytes / 1024).toFixed(0)} kB`;
    this.$("cam").textContent = camMode;
    this.el.classList.toggle("paused", !!paused);
  }
}
