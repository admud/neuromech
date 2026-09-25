"""BCI stand-in used while the headset engine or physical hardware is absent."""

import math
import threading
import time


TARGETS = ("up", "down", "left", "right")
DEFAULT_FREQS = dict(zip(TARGETS, (11.0, 14.0, 17.0, 20.0)))
VECTORS = {"up": (1, 0), "down": (-1, 0), "left": (0, 1), "right": (0, -1)}


class StubEngine:
    """Small thread-safe implementation of the BciEngine interface."""

    def __init__(self, settings=None):
        self.lock = threading.RLock()
        self.freqs = dict(getattr(settings, "freqs", DEFAULT_FREQS))
        self.params = {
            "window_s": getattr(settings, "window_s", 3.0),
            "margin": getattr(settings, "margin", 0.06),
            "dwell": getattr(settings, "dwell", 2),
            "speed": getattr(settings, "speed", 0.3),
        }
        self.armed = False
        self.reason = "startup"
        self.phone = False
        self.robot = False
        self.override = None
        self.override_until = 0.0
        self.gaze = None
        self.config_id = 1
        self.started = time.monotonic()

    def start(self):
        self.started = time.monotonic()

    def stop(self):
        pass

    def config_message(self):
        with self.lock:
            return {"type": "config", "config_id": self.config_id,
                    "targets": [{"id": k, "freq": self.freqs[k]} for k in TARGETS]}

    def _winner(self):
        return ("up", "right", "down", "left", None)[
            int((time.monotonic() - self.started) / 3) % 5]

    def command(self):
        with self.lock:
            direction = None
            source = "none"
            if self.armed:
                if time.monotonic() < self.override_until and self.override in TARGETS:
                    direction, source = self.override, "override"
                else:
                    direction, source = self._winner(), "bci"
            vx, vy = VECTORS.get(direction, (0, 0))
            speed = self.params["speed"]
            if direction is None:
                source = "none"
            return {"vx": vx * speed, "vy": vy * speed,
                    "direction": direction, "source": source}

    def status(self):
        with self.lock:
            winner = self._winner()
            scores = {k: round(0.32 + 0.04 * math.sin(time.monotonic()), 3)
                      if k == winner else 0.04 for k in TARGETS}
            return {"armed": self.armed, "disarm_reason": self.reason,
                    "winner": winner, "scores": scores, "command": self.command(),
                    "dwell": {"direction": winner, "count": self.params["dwell"] if winner else 0,
                              "needed": self.params["dwell"]},
                    "decode_ms": 8.0, "params": dict(self.params),
                    "eeg": {"device": "stub", "port": None, "fs": 250,
                            "channels": ["P7", "P8", "O1", "O2"], "ok": True,
                            "stalled_s": 0.0},
                    "sim": {"gaze": self.gaze}, "warnings": []}

    def handle(self, msg, source):
        kind = msg.get("type")
        with self.lock:
            if kind == "arm":
                self.armed = msg.get("armed") is True
                self.reason = None if self.armed else "user"
                if not self.armed:
                    self.override = None
                return False
            if kind == "override" and source == "dashboard":
                direction = msg.get("direction")
                self.override = direction if direction in TARGETS else None
                self.override_until = time.monotonic() + 0.5 if self.override else 0
                return False
            if kind == "sim_gaze" and source == "dashboard":
                self.gaze = msg.get("target") if msg.get("target") in TARGETS else None
                return False
            if kind == "set_config" and source == "dashboard":
                changed = False
                freqs = msg.get("freqs", {})
                if isinstance(freqs, dict):
                    for k, value in freqs.items():
                        if k in TARGETS and isinstance(value, (int, float)) and math.isfinite(value) and 4 <= value <= 40:
                            if self.freqs[k] != float(value):
                                self.freqs[k] = float(value)
                                changed = True
                for key, lo, hi in (("window_s", 0.5, 10), ("margin", 0, 1),
                                    ("dwell", 1, 10), ("speed", 0, 1)):
                    value = msg.get(key)
                    if isinstance(value, (int, float)) and math.isfinite(value) and lo <= value <= hi:
                        self.params[key] = int(value) if key == "dwell" else float(value)
                if changed:
                    self.config_id += 1
                return changed
        return False

    def set_phone_connected(self, connected):
        with self.lock:
            if self.phone and not connected:
                self.armed, self.reason = False, "phone_lost"
            self.phone = connected

    def set_robot_connected(self, connected):
        with self.lock:
            if self.robot and not connected:
                self.armed, self.reason = False, "robot_lost"
            self.robot = connected
