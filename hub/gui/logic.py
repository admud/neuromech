"""Window-free logic for the desktop GUI: flicker levels, layout, frame
statistics, the hold-to-arm and keyboard-drive state machines, and the
per-frame log. Kept apart from psychopy so it can be unit-tested headless.
"""
import math

import numpy as np

TARGETS = ("up", "down", "left", "right")
DEFAULT_FREQS = (11.0, 14.0, 17.0, 20.0)
TWO_PI = 2.0 * math.pi


def levels(freqs, t, out=None):
    """Luminance 0..1 per target at time t (seconds): 0.5*(1+sin(2*pi*f*t)).

    `t` must be the (predicted) flip time of the frame being drawn, never a
    frame count: design rule 1. `out` lets the render loop reuse one array.
    """
    if out is None:
        out = np.empty(len(freqs))
    for i, f in enumerate(freqs):
        out[i] = 0.5 * (1.0 + math.sin(TWO_PI * f * t))
    return out


def letterbox(src_w, src_h, box_w, box_h):
    """Largest (w, h) with the source aspect ratio that fits the box."""
    s = min(box_w / src_w, box_h / src_h)
    return src_w * s, src_h * s


class Layout:
    """Pixel layout, origin at the window centre, y up (psychopy 'pix').

    Circles sit on the four edges (top = forward, bottom = back, left,
    right), `margin` of the short side in from the edge, so they are as far
    apart as the screen allows: better SSVEP separation between targets.
    """

    def __init__(self, w, h, size=0.16, margin=0.03):
        self.w, self.h = float(w), float(h)
        short = min(w, h)
        self.radius = 0.5 * size * short
        m = margin * short
        dx = self.w / 2 - m - self.radius
        dy = self.h / 2 - m - self.radius
        self.centres = {"up": (0.0, dy), "down": (0.0, -dy),
                        "left": (-dx, 0.0), "right": (dx, 0.0)}

    def video_size(self, src_w, src_h):
        return letterbox(src_w, src_h, self.w, self.h)


class FrameStats:
    """Flip intervals over a window (for frame_stats) and over the whole run."""

    def __init__(self, period_s):
        self.period = period_s
        self.window = []
        self.total = 0
        self.late = 0          # intervals > 1.5 refresh periods, whole run
        self.max_ms = 0.0

    def add(self, dt_s):
        self.window.append(dt_s)
        self.total += 1
        if dt_s > 1.5 * self.period:
            self.late += 1
        if dt_s * 1000 > self.max_ms:
            self.max_ms = dt_s * 1000

    def summary(self, window_s):
        """frame_stats body for the last window, then start a new window.

        `dropped` = intervals > 1.5x the median, like the phone (protocol.md).
        """
        a = np.asarray(self.window) * 1000.0
        self.window = []
        if a.size == 0:
            return {"fps": 0.0, "p95_ms": 0.0, "dropped": 0, "window_s": round(window_s, 3)}
        med = float(np.median(a))
        return {"fps": round(a.size / window_s, 1),
                "p95_ms": round(float(np.percentile(a, 95)), 2),
                "dropped": int(np.sum(a > 1.5 * med)),
                "window_s": round(window_s, 3)}

    @property
    def late_pct(self):
        return 100.0 * self.late / self.total if self.total else 0.0


class ArmHold:
    """Hold Enter for `hold_s` to arm; fires once per press."""

    def __init__(self, hold_s=1.0):
        self.hold_s = hold_s
        self.since = None
        self.fired = False

    def press(self, t):
        if self.since is None:
            self.since, self.fired = t, False

    def release(self):
        self.since, self.fired = None, False

    def progress(self, t):
        """0..1 while held and not yet fired, else 0."""
        if self.since is None or self.fired:
            return 0.0
        return min(1.0, (t - self.since) / self.hold_s)

    def update(self, t):
        """True exactly once, when the hold completes."""
        if self.since is not None and not self.fired and t - self.since >= self.hold_s:
            self.fired = True
            return True
        return False


class DriveKeys:
    """Held drive keys; the most recently pressed one wins."""

    def __init__(self):
        self.held = []   # [(key, direction)], oldest first

    def press(self, key, direction):
        if all(k != key for k, _ in self.held):
            self.held.append((key, direction))

    def release(self, key):
        self.held = [(k, d) for k, d in self.held if k != key]

    def clear(self):
        self.held = []

    def current(self):
        return self.held[-1][1] if self.held else None


class OverrideSender:
    """Turns the held direction into `override` messages: immediately on a
    change, every `period_s` while held (the hub expires an override 500 ms
    after the last one), and one `null` on release."""

    def __init__(self, period_s=0.2):
        self.period = period_s
        self.sent = None
        self.last = -1e9

    def tick(self, now, direction):
        """Message to send now, or None."""
        if direction != self.sent or (direction and now - self.last >= self.period):
            self.sent, self.last = direction, now
            return {"type": "override", "direction": direction}
        return None


class FrameLog:
    """Per-frame record for --log-frames, kept in memory (no disk I/O in the
    render loop) and written as CSV at exit."""

    # work_ms: CPU time this thread spent on the frame (flip return -> next
    # flip call). Near 8.3 ms at 120 Hz would be our fault; late frames with
    # small work_ms come from outside (other processes, GPU contention).
    COLUMNS = (["frame", "t_pred", "t_flip"] + ["L_" + t for t in TARGETS] + ["f_" + t for t in TARGETS]
               + ["work_ms"])

    def __init__(self, path, chunk=120 * 60):
        self.path = path
        self.chunk = chunk
        self.rows = np.empty((chunk, len(self.COLUMNS)))
        self.n = 0

    def add(self, frame, t_pred, t_flip, lv, freqs, work_ms=0.0):
        if self.n == len(self.rows):
            self.rows = np.concatenate([self.rows, np.empty((self.chunk, len(self.COLUMNS)))])
        r = self.rows[self.n]
        r[0], r[1], r[2] = frame, t_pred, t_flip
        r[3:7] = lv
        r[7:11] = freqs
        r[11] = work_ms
        self.n += 1

    def save(self):
        np.savetxt(self.path, self.rows[:self.n], delimiter=",", header=",".join(self.COLUMNS),
                   comments="", fmt=["%d", "%.6f", "%.6f"] + ["%.4f"] * 4 + ["%.3f"] * 4 + ["%.3f"])
        return self.n


class LatchView:
    """What the latch-mode overlays show, derived from `state` (Phase 6).

    Engine fields (all optional; absent = hold mode, nothing latched):
    - control_mode "hold"|"latch", latched (direction or null);
    - latch {elapsed_s, max_s, left_s} while latched (the timer bar);
    - clench {z, threshold, fired_at, count, last {t, result, direction}},
      result one of latched / unlatched / no_target / not_armed / hold_mode.
    Fallbacks from the first proposal: latched_at + params.latch_max_s for
    the timer, clench.ignored_at for "no target". Times are t_hub.

    Events are detected as *changes* (of clench.last.t, else fired_at), so a
    stale event seen on connect doesn't flash, and each shows for a fixed time.
    """

    def __init__(self, flash_s=0.4, no_target_s=1.5, recent_s=1.0):
        self.flash_s, self.recent_s = flash_s, recent_s
        self.notice_s = {"no_target": no_target_s, "not_armed": no_target_s}
        self._event = self._ignored = None
        self._seen = False
        self.flash_until = -1.0
        self.notice, self.notice_until = None, -1.0

    def update(self, s, now, t_hub):
        """s: state dict or None; now: monotonic seconds; t_hub: interpolated hub time or None."""
        s = s or {}
        mode = s.get("control_mode") or "hold"
        latched = s.get("latched") if s.get("latched") in TARGETS else None
        clench = s.get("clench") if isinstance(s.get("clench"), dict) else {}
        last = clench.get("last") if isinstance(clench.get("last"), dict) else None
        event_t = last.get("t") if last else clench.get("fired_at")
        ignored = clench.get("ignored_at")
        if self._seen:
            if event_t is not None and event_t != self._event and self._recent(event_t, t_hub):
                self.flash_until = now + self.flash_s
                result = last.get("result") if last else None
                if result in self.notice_s:
                    self.notice, self.notice_until = result, now + self.notice_s[result]
            if ignored is not None and ignored != self._ignored and self._recent(ignored, t_hub):
                self.notice, self.notice_until = "no_target", now + self.notice_s["no_target"]
        if s:
            self._event, self._ignored, self._seen = event_t, ignored, True

        frac = remaining = None
        latch = s.get("latch") if isinstance(s.get("latch"), dict) else None
        params = s.get("params") if isinstance(s.get("params"), dict) else {}
        t_state = s.get("t_hub")
        age = t_hub - t_state if t_hub is not None and isinstance(t_state, (int, float)) else 0.0
        if latched and latch and isinstance(latch.get("left_s"), (int, float)) and latch.get("max_s"):
            remaining = max(0.0, latch["left_s"] - age)     # interpolated between 10 Hz states
            frac = remaining / latch["max_s"]
        elif latched and isinstance(s.get("latched_at"), (int, float)) and t_hub is not None:
            max_s = params.get("latch_max_s") or 3.0
            remaining = max(0.0, max_s - (t_hub - s["latched_at"]))
            frac = remaining / max_s
        notice = self.notice if now < self.notice_until and latched is None else None
        return {"mode": mode, "latched": latched,
                "preview": mode == "latch" and latched is None,
                "flash": now < self.flash_until,
                "notice": notice,                       # "no_target" | "not_armed" | None
                "no_target": notice == "no_target",
                "frac": frac, "remaining_s": remaining}

    def _recent(self, t_event, t_hub):
        return t_hub is None or t_hub - t_event <= self.recent_s
