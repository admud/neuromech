"""BciEngine: board + decoder + arbiter, behind the interface in plan/protocol.md.

Threads:
  - the decoder (ssvep_bci.Decoder subclass) decodes every `interval_s` and
    hands each completed decode to the engine exactly once, via a callback;
  - the engine loop (every 50 ms) does the stall check, quality, and decoder
    rebuilds after a config change.
Public methods other than start/stop take one lock, do no I/O and return in
well under 1 ms, since the server calls them from its asyncio loop.
"""
import sys
import threading
import time

import numpy as np

from . import board as boardmod   # also puts control/ on sys.path via hub.bci
from .arbiter import MODES, Arbiter
from .clench import ClenchDetector, pick_clench_channels
from .config import DIRECTIONS, EngineSettings

from ssvep_bci import Decoder, harmonic_clashes  # noqa: E402  (control/, read-only)

LOOP_S = 0.05
STALL_S = 1.5          # newest sample unchanged this long -> eeg_stall
QUALITY_S = 1.0
RAIL_UV = 180000.0     # the Cyton rails at +-187500 µV
MAX_FREQ_WARN = 40.0   # 120 Hz / 3: fewer than 3 frames per cycle on the phone

LIMITS = {"window_s": (0.5, 6.0), "margin": (0.0, 1.0), "dwell": (1, 10), "speed": (0.0, 1.0),
          "clench_threshold": (1.0, 500.0), "latch_max_s": (0.5, 30.0)}
CLENCH_Z_SHOW_S = 0.2  # state.clench.z is the peak over this long, so a meter sees bursts
FREQ_RANGE = (5.0, 40.0)


class SeqDecoder(Decoder):
    """ssvep_bci.Decoder that reports each completed decode exactly once.

    Decoder._step returns early while the buffer fills and otherwise stores a
    fresh scores array, so a changed array identity means a real decode.
    """

    def __init__(self, *args, on_decode=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.seq = 0
        self._on_decode = on_decode

    def _step(self, t0):
        with self._lock:
            before = self._scores
        super()._step(t0)
        with self._lock:
            if self._scores is before:
                return
            self.seq += 1
            scores, winner, ms = self._scores.copy(), self._winner, self._decode_ms
        if self._on_decode is not None and self._running:
            self._on_decode(scores, winner, ms)


def _log(msg):
    print("[engine] %s" % msg, file=sys.stderr, flush=True)


class BciEngine:
    settle_s = 3.0   # stream settle time in start(); tests shorten it

    def __init__(self, settings: EngineSettings) -> None:
        self.settings = settings
        self._lock = threading.Lock()
        self._arbiter = Arbiter(settings.dwell, settings.speed, settings.control_mode,
                                settings.latch_max_s)

        self._armed = False
        self._disarm_reason = "startup"
        self._phone = False
        self._robot = False

        self._scores = {d: 0.0 for d in DIRECTIONS}
        self._winner = None
        self._decode_ms = 0.0
        self._last_decode_t = None

        self._ob = None             # boardmod.OpenBoard once started
        self._started = False
        self._last_sample = None
        self._last_change_t = 0.0
        self._last_tick_t = None    # engine loop's previous tick
        self._quality = []
        self._sim_gaze = None
        self._config_id = 1
        self._model = None
        self._model_freqs = None
        self._mode = "cca"
        self._model_warning = None

        # Phase 6 clench detection (the detector itself is engine-loop only)
        self._clench = None         # ClenchDetector once started
        self._clench_rows = []
        self._clench_names = []
        self._clench_seen = None    # last board column fed to the detector
        self._clench_z = []         # (t, peak z) of recent passes
        self._clench_count = 0
        self._clench_fired_at = None
        self._clench_ignored_at = None   # last clench that found no target
        self._clench_event = None   # {"t", "result", "direction"}

        self._decoder = None
        self._gen = 0               # bumps on every decoder-affecting change
        self._rebuild = False
        self._loop_thread = None
        self._running = False

    # ---- lifecycle -------------------------------------------------------
    def start(self) -> None:
        s = self.settings
        ob = boardmod.open_board(s)
        _log("%s%s @ %d Hz, decoding %s" % (ob.device, " on %s" % ob.port if ob.port else "",
                                             ob.fs, ", ".join(ob.ch_names)))
        if s.model_path:
            self._load_model(ob)
        self._clench_names, self._clench_rows = pick_clench_channels(
            ob.all_names or ob.ch_names, ob.all_rows or ob.ch_rows, s.clench_channels)
        self._clench = ClenchDetector(ob.fs, len(self._clench_rows), threshold=s.clench_threshold)
        _log("clench detection on %s, %s mode" % (", ".join(self._clench_names), s.control_mode))
        ob.board.start_stream()
        with self._lock:
            self._ob = ob
            self._last_change_t = time.monotonic()
        _log("stream started, settling %.0f s" % self.settle_s)
        time.sleep(self.settle_s)
        with self._lock:
            self._started = True
            self._last_change_t = time.monotonic()
            gen = self._gen
        self._install_decoder(gen)
        self._running = True
        self._loop_thread = threading.Thread(target=self._loop, name="bci-engine", daemon=True)
        self._loop_thread.start()

    def stop(self) -> None:
        self._running = False
        if self._loop_thread is not None:
            self._loop_thread.join(timeout=1.0)
        with self._lock:
            dec, self._decoder = self._decoder, None
            self._started = False
            self._armed = False
            self._disarm_reason = "startup"
            ob = self._ob
        if dec is not None:
            dec.stop()
            dec.join(timeout=2.0)
        if ob is not None:
            for fn in (ob.board.stop_stream, ob.board.release_session):
                try:
                    fn()
                except Exception:
                    pass

    # ---- interface for the server ---------------------------------------
    def config_message(self) -> dict:
        with self._lock:
            return {"type": "config", "config_id": self._config_id,
                    "targets": [{"id": d, "freq": float(self.settings.freqs[d])}
                                for d in DIRECTIONS]}

    def status(self) -> dict:
        now = time.monotonic()
        with self._lock:
            self._check_stall(now)
            s, ob = self.settings, self._ob
            stalled = self._stalled_s(now)
            return {
                "armed": self._armed,
                "disarm_reason": self._disarm_reason,
                "winner": self._winner,
                "scores": dict(self._scores),
                "command": self._command(now),
                "dwell": self._arbiter.dwell_status(),
                "decode_ms": round(self._decode_ms, 1),
                "params": {"window_s": s.window_s, "margin": s.margin,
                           "dwell": s.dwell, "speed": s.speed,
                           "control_mode": s.control_mode,
                           "clench_threshold": s.clench_threshold,
                           "latch_max_s": s.latch_max_s},
                "eeg": {"device": s.device, "port": ob.port if ob else s.port,
                        "fs": ob.fs if ob else None,
                        "channels": list(ob.ch_names) if ob else [],
                        "ok": self._eeg_ok(now), "stalled_s": round(stalled, 2),
                        "quality": list(self._quality)},
                "sim": {"gaze": self._sim_gaze} if s.device == "sim" else None,
                "warnings": self._warnings(),
                "control_mode": s.control_mode,
                "latched": self._arbiter.latched,
                "latched_at": self._arbiter.latched_at,
                "latch": self._arbiter.latch_status(now),
                "clench": {"z": round(max([z for t, z in self._clench_z
                                            if now - t <= CLENCH_Z_SHOW_S] or [0.0]), 1),
                           "threshold": s.clench_threshold, "count": self._clench_count,
                           "fired_at": self._clench_fired_at,
                           "ignored_at": self._clench_ignored_at,
                           "last": dict(self._clench_event) if self._clench_event else None,
                           "channels": list(self._clench_names)},
            }

    def command(self) -> dict:
        now = time.monotonic()
        with self._lock:
            self._check_stall(now)
            return self._command(now)

    def set_phone_connected(self, connected: bool) -> None:
        with self._lock:
            was, self._phone = self._phone, bool(connected)
            if was and not connected:
                self._disarm("phone_lost")

    def set_robot_connected(self, connected: bool) -> None:
        with self._lock:
            was, self._robot = self._robot, bool(connected)
            if was and not connected:
                self._disarm("robot_lost")

    def handle(self, msg: dict, source: str) -> bool:
        """Apply a client message. Returns True only if the target freqs changed."""
        kind = msg.get("type") if isinstance(msg, dict) else None
        try:
            if kind == "arm" and source in ("phone", "dashboard"):
                self._handle_arm(msg)
            elif kind == "override" and source == "dashboard":
                self._handle_override(msg)
            elif kind == "sim_gaze" and source == "dashboard":
                self._handle_sim_gaze(msg)
            elif kind == "sim_clench" and source == "dashboard":
                self._handle_sim_clench(msg)
            elif kind == "set_config" and source == "dashboard":
                return self._handle_set_config(msg)
        except (TypeError, ValueError, KeyError) as exc:
            _log("ignored %s from %s: %s" % (kind, source, exc))
        return False

    # ---- handlers --------------------------------------------------------
    def _handle_arm(self, msg):
        want = msg.get("armed")
        if not isinstance(want, bool):
            raise ValueError("armed must be a bool")
        now = time.monotonic()
        with self._lock:
            if not want:
                self._disarm("user")
                return
            self._check_stall(now)
            if not self._eeg_ok(now):
                _log("arm refused: EEG not ok")
                return
            if not self._armed:
                # A direction must dwell afresh after arming.
                self._arbiter.reset_dwell()
                self._arbiter.clear_override()
                self._arbiter.unlatch()
            self._armed = True
            self._disarm_reason = None

    def _handle_override(self, msg):
        direction = msg.get("direction")
        if direction is not None and direction not in DIRECTIONS:
            raise ValueError("bad direction %r" % (direction,))
        with self._lock:
            if not self._armed and direction is not None:
                return   # needs armed; don't let a stale key press fire on arming
            self._arbiter.set_override(direction, time.monotonic())

    def _handle_sim_gaze(self, msg):
        target = msg.get("target")
        if target is not None and target not in DIRECTIONS:
            raise ValueError("bad target %r" % (target,))
        with self._lock:
            ob = self._ob
            if self.settings.device != "sim" or ob is None:
                return
            self._sim_gaze = target
        ob.board.set_gaze(None if target is None else DIRECTIONS.index(target))

    def _handle_sim_clench(self, msg):
        dur = min(2.0, max(0.1, _num(msg.get("duration_s", 0.6), "duration_s")))
        with self._lock:
            ob = self._ob
            if self.settings.device != "sim" or ob is None:
                return
        ob.board.clench(dur)

    def _handle_set_config(self, msg):
        with self._lock:
            new = self._validate(msg)   # raises before anything changes
            s = self.settings
            freqs_changed = "freqs" in new and new["freqs"] != s.freqs
            decoder_changed = freqs_changed or any(
                k in new and new[k] != getattr(s, k) for k in ("window_s", "margin"))
            for k, v in new.items():
                setattr(s, k, v)
            self._arbiter.dwell = s.dwell
            self._arbiter.speed = s.speed
            self._arbiter.latch_max_s = s.latch_max_s
            if s.control_mode != self._arbiter.mode:
                self._arbiter.mode = s.control_mode
                self._arbiter.unlatch()
                _log("control mode: %s" % s.control_mode)
            if self._clench is not None:
                self._clench.threshold = s.clench_threshold
            if "dwell" in new:
                self._arbiter.reset_dwell()
            if decoder_changed:
                # Old decoder's results are dropped from now on; the loop
                # thread builds the new one (keeps this call fast).
                self._gen += 1
                self._rebuild = True
                self._arbiter.reset_dwell()
                self._winner = None
                self._scores = {d: 0.0 for d in DIRECTIONS}
                self._last_decode_t = None
            if freqs_changed:
                self._config_id += 1
            ob = self._ob
        if freqs_changed and ob is not None and self.settings.device == "sim":
            ob.board.set_freqs([self.settings.freqs[d] for d in DIRECTIONS])
        return freqs_changed

    def _validate(self, msg):
        s, out = self.settings, {}
        if "freqs" in msg:
            given = msg["freqs"]
            if not isinstance(given, dict) or any(k not in DIRECTIONS for k in given):
                raise ValueError("freqs must map up/down/left/right to Hz")
            freqs = dict(s.freqs)
            for k, v in given.items():
                v = _num(v, "freqs.%s" % k)
                if not FREQ_RANGE[0] <= v <= FREQ_RANGE[1]:
                    raise ValueError("freq %s=%g outside %g-%g Hz" % ((k, v) + FREQ_RANGE))
                freqs[k] = v
            if len({round(freqs[d], 6) for d in DIRECTIONS}) != len(DIRECTIONS):
                raise ValueError("freqs must be distinct")
            out["freqs"] = {d: freqs[d] for d in DIRECTIONS}
        if "control_mode" in msg:
            if msg["control_mode"] not in MODES:
                raise ValueError("control_mode must be hold or latch")
            out["control_mode"] = msg["control_mode"]
        for key, (lo, hi) in LIMITS.items():
            if key not in msg:
                continue
            v = msg[key]
            if key == "dwell":
                if isinstance(v, bool) or not isinstance(v, (int, float)) or v != int(v):
                    raise ValueError("dwell must be an integer")
                v = int(v)
            else:
                v = _num(v, key)
            if not lo <= v <= hi:
                raise ValueError("%s=%g outside %g-%g" % (key, v, lo, hi))
            out[key] = v
        return out

    # ---- decoder ---------------------------------------------------------
    def _load_model(self, ob):
        from ssvep_trca import FilterBankTRCA, load_calibration
        s = self.settings
        cal = load_calibration(s.model_path)
        n = int(s.window_s * cal["fs"])
        if n > cal["epochs"].shape[2]:
            _log("window %.1fs exceeds the %.1fs calibration trials; clamping"
                 % (s.window_s, cal["trial_len"]))
            n = cal["epochs"].shape[2]
        if cal["ch_names"] != list(ob.ch_names):
            _log("calibration channels %s != live channels %s" % (cal["ch_names"], ob.ch_names))
        mode = s.mode
        if mode == "trca":
            # Phone flicker isn't phase-locked to the EEG; full TRCA can't work live.
            _log("'trca' needs phase-locked windows; using trca_cca")
            mode = "trca_cca"
        self._model = FilterBankTRCA(cal["freqs"], cal["fs"]).fit(
            cal["epochs"][:, :, :n], cal["labels"])
        self._model_freqs = [float(f) for f in cal["freqs"]]
        self._mode = mode
        _log("trained decoder: %s, %d calibration trials" % (mode, len(cal["labels"])))

    def _install_decoder(self, gen):
        """Build and start a decoder for the current settings (no engine lock held while building)."""
        with self._lock:
            s, ob = self.settings, self._ob
            freqs = [float(s.freqs[d]) for d in DIRECTIONS]
            window_s, margin, interval = s.window_s, s.margin, s.interval_s
        model, mode = None, "cca"
        self._model_warning = None
        if self._model is not None:
            if freqs == self._model_freqs:
                model, mode = self._model, self._mode
            else:
                self._model_warning = "freqs differ from the calibration; using plain CCA"
        dec = SeqDecoder(ob.board, ob.fs, ob.ch_rows, freqs, window_s, margin,
                         interval=interval, model=model, mode=mode,
                         on_decode=lambda sc, w, ms: self._on_decode(gen, sc, w, ms))
        with self._lock:
            if gen != self._gen:
                return  # superseded while building; the loop will rebuild
            old, self._decoder = self._decoder, dec
            self._rebuild = False
        dec.start()
        if old is not None:
            old.stop()

    def _on_decode(self, gen, scores, winner, decode_ms):
        with self._lock:
            if gen != self._gen:
                return   # a decoder that has been replaced
            self._scores = {d: round(float(scores[i]), 4) for i, d in enumerate(DIRECTIONS)}
            self._winner = None if winner is None else DIRECTIONS[winner]
            self._decode_ms = decode_ms
            self._last_decode_t = time.monotonic()
            self._arbiter.on_decode(self._winner, self._last_decode_t)

    # ---- engine loop -----------------------------------------------------
    def _loop(self):
        next_quality = time.monotonic() + QUALITY_S
        while self._running:
            t0 = time.monotonic()
            try:
                self._tick(t0, t0 >= next_quality)
            except Exception as exc:
                _log("loop %s: %s" % (type(exc).__name__, exc))
            if t0 >= next_quality:
                next_quality = t0 + QUALITY_S
            time.sleep(max(0.0, LOOP_S - (time.monotonic() - t0)))

    def _tick(self, now, do_quality):
        with self._lock:
            ob, rebuild, gen = self._ob, self._rebuild, self._gen
            # The whole process was frozen (suspended, debugger, sleep): the
            # EEG would look fresh again as soon as the board catches up, so
            # treat the gap itself as a stall rather than resume armed.
            if self._last_tick_t is not None and now - self._last_tick_t > STALL_S:
                _log("engine loop stalled %.1f s" % (now - self._last_tick_t))
                self._disarm("eeg_stall")
            self._last_tick_t = now
        if ob is None:
            return
        if rebuild:
            self._install_decoder(gen)

        newest = ob.board.get_current_board_data(1)
        with self._lock:
            if newest.shape[1] > 0:
                col = newest[:, -1]
                if self._last_sample is None or not np.array_equal(col, self._last_sample):
                    self._last_sample = col.copy()
                    self._last_change_t = time.monotonic()
            self._check_stall(time.monotonic())
            if self._arbiter.expire(time.monotonic()):
                _log("latch released: latch_max_s")

        self._clench_tick(ob)

        if do_quality:
            data = ob.board.get_current_board_data(int(ob.fs))
            q = []
            if data.shape[1] > 1:
                for name, row in zip(ob.ch_names, ob.ch_rows):
                    x = data[row]
                    q.append({"name": name, "std_uv": round(float(np.std(x)), 1),
                              "railed": bool(np.max(np.abs(x)) > RAIL_UV)})
            with self._lock:
                self._quality = q

    def _clench_tick(self, ob):
        """Feed the clench detector the samples that arrived since the last pass."""
        det = self._clench
        if det is None:
            return
        data = ob.board.get_current_board_data(int(ob.fs))
        if data.shape[1] == 0:
            return
        new = data
        if self._clench_seen is not None:
            # get_current_board_data doesn't consume (the decoder reads the same
            # buffer), so find the last column already seen. Not found = more
            # than 1 s since the last pass: take the whole second.
            hits = np.nonzero(np.all(data == self._clench_seen[:, None], axis=0))[0]
            if hits.size:
                new = data[:, hits[-1] + 1:]
        if new.shape[1] == 0:
            return
        self._clench_seen = data[:, -1].copy()
        t_read = time.monotonic()
        fires = det.update(new[self._clench_rows])
        with self._lock:
            self._clench_z = [(t, z) for t, z in self._clench_z if t_read - t <= 1.0]
            self._clench_z.append((t_read, det.z_peak))
            for off in fires:
                onset = t_read - (new.shape[1] - off) / ob.fs
                self._on_clench(onset, t_read)

    def _on_clench(self, onset, now):
        """One detected clench. Caller holds the lock."""
        self._clench_count += 1
        self._clench_fired_at = now
        if self._arbiter.mode != "latch":
            result, d = "hold_mode", None
        elif not self._armed:
            result, d = "not_armed", None   # nothing may latch while disarmed
        else:
            result, d = self._arbiter.clench(onset, now)
        self._clench_event = {"t": now, "result": result, "direction": d}
        if result == "no_target":
            self._clench_ignored_at = now
        _log("clench #%d: %s%s" % (self._clench_count, result, " " + d if d else ""))

    # ---- helpers (caller holds the lock) ---------------------------------
    def _stalled_s(self, now):
        if not self._started:
            return 0.0
        return max(0.0, now - self._last_change_t)

    def _eeg_ok(self, now):
        return self._started and self._stalled_s(now) <= STALL_S

    def _check_stall(self, now):
        if self._armed and self._started and not self._eeg_ok(now):
            self._disarm("eeg_stall")

    def _disarm(self, reason):
        # An explicit STOP always records "user"; auto-disarms only matter when armed.
        if self._armed or reason == "user":
            self._armed = False
            self._disarm_reason = reason
            self._arbiter.clear_override()
            self._arbiter.unlatch()

    def _command(self, now):
        s = self.settings
        # Decodes stopped arriving (decoder stuck): don't keep an old direction.
        fresh = (self._last_decode_t is not None
                 and now - self._last_decode_t <= max(1.0, 4 * s.interval_s))
        if not fresh and self._arbiter.active is not None:
            self._arbiter.reset_dwell()
        return self._arbiter.command(self._armed, self._eeg_ok(now), now)

    def _warnings(self):
        freqs = [self.settings.freqs[d] for d in DIRECTIONS]
        w = ["%g and %g Hz share a harmonic at %g Hz" % c for c in harmonic_clashes(freqs)]
        w += ["%g Hz is above %g Hz (120 Hz / 3)" % (f, MAX_FREQ_WARN)
              for f in freqs if f > MAX_FREQ_WARN]
        if self._model_warning:
            w.append(self._model_warning)
        if self.settings.device == "synthetic":
            # brainflow's synthetic board is a sine at 5 Hz x channel number on
            # every channel (C4 = 20 Hz), so it "looks at" a target all the time.
            w.append("synthetic board: test sines, not EEG (C4 is a 20 Hz sine and decodes "
                     "as a target); use --device sim for realistic behaviour")
        return w


def _num(v, name):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not np.isfinite(v):
        raise ValueError("%s must be a number" % name)
    return float(v)
