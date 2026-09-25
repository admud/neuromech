"""Turns decoder output into a safe velocity command.

Pure logic: no threads, no I/O, no clock. Callers pass `now` (monotonic
seconds) so tests can drive time. The engine serialises access with its lock.

Priority, highest first:
  1. not armed      -> zero, source "none"
  2. override live  -> the override direction, source "override"
  3. EEG not ok     -> zero
  4. BCI            -> the dwelled direction, else zero (look away = stop)
"""
from .config import DIRECTIONS

OVERRIDE_TTL_S = 0.5

# Unit vectors in ROS axes: vx forward+, vy left+.
_AXES = {"up": (1.0, 0.0), "down": (-1.0, 0.0), "left": (0.0, 1.0), "right": (0.0, -1.0)}


def velocity(direction, speed):
    """(vx, vy) for a direction id, or (0, 0) for None."""
    if direction is None:
        return 0.0, 0.0
    ax, ay = _AXES[direction]
    return ax * speed + 0.0, ay * speed + 0.0  # + 0.0 turns -0.0 into 0.0


class Arbiter:
    def __init__(self, dwell=2, speed=0.3):
        self.dwell = int(dwell)
        self.speed = float(speed)
        self._candidate = None   # current decoder winner being dwelled on
        self._count = 0          # consecutive decodes it has won
        self._override = None    # direction
        self._override_until = 0.0

    # ---- inputs ----------------------------------------------------------
    def on_decode(self, winner):
        """Feed one completed decode's winner (direction id or None). Call once per decode."""
        if winner is not None and winner not in _AXES:
            raise ValueError("unknown direction %r" % winner)
        if winner is None:
            self._candidate, self._count = None, 0
        elif winner == self._candidate:
            self._count += 1
        else:
            # A different target starts dwelling from scratch; the old one drops now.
            self._candidate, self._count = winner, 1

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
