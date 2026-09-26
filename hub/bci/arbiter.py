"""Turns decoder output into a safe velocity command.

Pure logic: no threads, no I/O, no clock. Callers pass `now` (monotonic
seconds) so tests can drive time. The engine serialises access with its lock.

Priority, highest first:
  1. not armed      -> zero, source "none"
  2. override live  -> the override direction, source "override"
  3. EEG not ok     -> zero
  4. BCI, by control mode:
     hold   the dwelled direction, else zero (look away = stop)
     latch  gaze only previews. A jaw clench latches the direction that was
            dwelled just before it; the robot keeps going that way (gaze is
            free) until a second clench, STOP/disarm, or latch_max_s.
"""
from collections import deque

from .config import DIRECTIONS

OVERRIDE_TTL_S = 0.5
# A clench latches the newest dwelled winner decoded within this long before
# the clench started. Decodes after the onset are skipped: the clench's EMG
# is in their window.
LATCH_LOOKBACK_S = 0.5
MODES = ("hold", "latch")

# Unit vectors in ROS axes: vx forward+, vy left+.
_AXES = {"up": (1.0, 0.0), "down": (-1.0, 0.0), "left": (0.0, 1.0), "right": (0.0, -1.0)}


def velocity(direction, speed):
    """(vx, vy) for a direction id, or (0, 0) for None."""
    if direction is None:
        return 0.0, 0.0
    ax, ay = _AXES[direction]
    return ax * speed + 0.0, ay * speed + 0.0  # + 0.0 turns -0.0 into 0.0


class Arbiter:
    def __init__(self, dwell=2, speed=0.3, mode="hold", latch_max_s=3.0):
        self.dwell = int(dwell)
        self.speed = float(speed)
        if mode not in MODES:
            raise ValueError("unknown control mode %r" % mode)
        self.mode = mode
        self.latch_max_s = float(latch_max_s)
        self._latched = None     # latched direction (latch mode)
        self._latched_at = 0.0
        self._history = deque(maxlen=16)   # (decode time, dwelled direction or None)
        self._candidate = None   # current decoder winner being dwelled on
        self._count = 0          # consecutive decodes it has won
        self._override = None    # direction
        self._override_until = 0.0

    # ---- inputs ----------------------------------------------------------
    def on_decode(self, winner, now=None):
        """Feed one completed decode's winner (direction id or None). Call once per decode.
        `now` (the decode's time) is needed for latch mode's look-back."""
        if winner is not None and winner not in _AXES:
            raise ValueError("unknown direction %r" % winner)
        if winner is None:
            self._candidate, self._count = None, 0
        elif winner == self._candidate:
            self._count += 1
        else:
            # A different target starts dwelling from scratch; the old one drops now.
            self._candidate, self._count = winner, 1
        if now is not None:
            self._history.append((now, self.active))

    def clench(self, onset, now):
        """A jaw clench that started at `onset`. Returns (result, direction):
        latched / unlatched / no_target, or hold_mode when not in latch mode.
        The caller handles "not armed" (nothing may latch while disarmed)."""
        if self.mode != "latch":
            return "hold_mode", None
        if self._latched is not None:
            d = self._latched
            self.unlatch()
            return "unlatched", d
        for t, d in reversed(self._history):
            if t > onset:
                continue            # decoded with the clench's EMG in the window
            if t < onset - LATCH_LOOKBACK_S:
                break
            if d is not None:
                self._latched, self._latched_at = d, now
                return "latched", d
        return "no_target", None

    def unlatch(self):
        self._latched = None

    @property
    def latched(self):
        return self._latched

    @property
    def latched_at(self):
        """When the current latch started (the caller's clock), or None."""
        return self._latched_at if self._latched is not None else None

    def expire(self, now):
        """Drop a latch older than latch_max_s. Returns True if it just expired."""
        if self._latched is not None and now - self._latched_at >= self.latch_max_s:
            self._latched = None
            return True
        return False

    def latch_status(self, now):
        if self._latched is None:
            return None
        el = max(0.0, now - self._latched_at)
        return {"elapsed_s": round(el, 2), "max_s": self.latch_max_s,
                "left_s": round(max(0.0, self.latch_max_s - el), 2)}

    def reset_dwell(self):
        self._candidate, self._count = None, 0

    def set_override(self, direction, now):
        """Keyboard drive. None clears it at once; otherwise it lives OVERRIDE_TTL_S."""
        if direction is None:
            self.clear_override()
            return
        if direction not in _AXES:
            raise ValueError("unknown direction %r" % direction)
        self._override = direction
        self._override_until = now + OVERRIDE_TTL_S

    def clear_override(self):
        self._override, self._override_until = None, 0.0

    # ---- outputs ---------------------------------------------------------
    @property
    def active(self):
        """The BCI direction that has dwelled long enough, or None."""
        if self._candidate is not None and self._count >= self.dwell:
            return self._candidate
        return None

    def override_active(self, now):
        return self._override is not None and now < self._override_until

    def command(self, armed, eeg_ok, now):
        if not armed:
            return _cmd(None, self.speed, "none")
        if self.override_active(now):
            return _cmd(self._override, self.speed, "override")
        if not eeg_ok:
            return _cmd(None, self.speed, "none")
        if self.mode == "latch":
            self.expire(now)
            d = self._latched
            return _cmd(d, self.speed, "bci" if d else "none")
        direction = self.active
        return _cmd(direction, self.speed, "bci" if direction else "none")

    def dwell_status(self):
        return {"direction": self._candidate,
                "count": min(self._count, self.dwell) if self._candidate else 0,
                "needed": self.dwell}


def _cmd(direction, speed, source):
    vx, vy = velocity(direction, speed)
    return {"vx": vx, "vy": vy, "direction": direction, "source": source}


assert list(_AXES) == DIRECTIONS
