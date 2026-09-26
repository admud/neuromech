"""Window-free logic of the desktop GUI (hub/gui/logic.py, hub/gui/analyze.py)."""
import math

import numpy as np

from hub.gui import analyze
from hub.gui.logic import (DEFAULT_FREQS, TARGETS, ArmHold, DriveKeys, FrameLog, FrameStats,
                           Layout, OverrideSender, letterbox, levels)


def test_levels_follow_the_formula_and_depend_only_on_time():
    for t in (0.0, 0.0123, 1.5, 3600.25):
        lv = levels(DEFAULT_FREQS, t)
        for f, L in zip(DEFAULT_FREQS, lv):
            assert math.isclose(L, 0.5 * (1 + math.sin(2 * math.pi * f * t)), abs_tol=1e-12)
    # Same time -> same levels, however many frames were drawn in between.
    out = np.empty(4)
    a = levels(DEFAULT_FREQS, 2.0, out).copy()
    for _ in range(7):
        levels(DEFAULT_FREQS, 1.0, out)
    assert np.array_equal(levels(DEFAULT_FREQS, 2.0, out), a)
    assert np.all((a >= 0) & (a <= 1))


def test_layout_circles_on_edges_inside_screen_and_apart():
    lay = Layout(2560, 1440, size=0.16, margin=0.03)
    assert math.isclose(lay.radius, 0.08 * 1440)
    c = lay.centres
    assert c["up"][1] > 0 and c["down"][1] < 0 and c["left"][0] < 0 and c["right"][0] > 0
    assert c["up"][0] == 0 and c["left"][1] == 0
    ring = lay.radius * 1.16          # outermost thing drawn around a circle (winner ring)
    for x, y in c.values():
        assert abs(x) + lay.radius <= 1280 and abs(y) + lay.radius <= 720
    ids = list(TARGETS)
    for i in range(4):
        for j in range(i + 1, 4):
            (x1, y1), (x2, y2) = c[ids[i]], c[ids[j]]
            assert math.hypot(x1 - x2, y1 - y2) > 2 * ring


def test_letterbox_keeps_aspect():
    assert letterbox(640, 480, 2560, 1440) == (1920, 1440)
    w, h = letterbox(640, 480, 1000, 2000)
    assert math.isclose(w, 1000) and math.isclose(h, 750)


def test_frame_stats_summary_and_late_count():
    fs = FrameStats(1 / 120)
    for _ in range(118):
        fs.add(1 / 120)
    fs.add(2 / 120)                   # one dropped frame
    s = fs.summary(1.0)
    assert s["fps"] == 119.0 and s["dropped"] == 1 and s["window_s"] == 1.0
    assert 8.3 < s["p95_ms"] < 8.4
    assert fs.late == 1 and fs.total == 119 and math.isclose(fs.late_pct, 100 / 119)
    assert fs.summary(1.0)["fps"] == 0.0        # window restarted


def test_arm_hold_needs_a_full_second_and_fires_once():
    h = ArmHold(1.0)
    h.press(10.0)
    assert not h.update(10.5) and 0.49 < h.progress(10.5) < 0.51
    h.release()                                  # let go early: nothing
    assert not h.update(11.2) and h.progress(11.2) == 0
    h.press(20.0)
    h.press(20.4)                                # key repeat doesn't restart the hold
    assert not h.update(20.9)
    assert h.update(21.0)
    assert not h.update(21.5) and h.progress(21.5) == 0   # once per press
    h.release()
    h.press(30.0)
    assert h.update(31.0)


def test_drive_keys_newest_wins_and_release():
    d = DriveKeys()
    assert d.current() is None
    d.press("UP", "up")
    d.press("A", "left")
    assert d.current() == "left"
    d.press("UP", "up")                          # repeat: no reorder
    assert d.current() == "left"
    d.release("A")
    assert d.current() == "up"
    d.clear()
    assert d.current() is None


def test_override_sender_immediate_periodic_and_single_null():
    o = OverrideSender(0.2)
    sent = []
    for frame in range(360):               # 3 s at 120 Hz; up held from 1.0 to 2.0 s
        t = frame / 120
        direction = "up" if 120 <= frame < 240 else None
        m = o.tick(t, direction)
        if m:
            sent.append((round(t, 3), m["direction"]))
    ups = [s for s in sent if s[1] == "up"]
    assert ups[0][0] == 1.0                      # immediately on press
    gaps = np.diff([s[0] for s in ups])
    assert np.all(gaps < 0.25) and len(ups) == 5  # every ~200 ms while held
    assert [s for s in sent if s[1] is None] == [(2.0, None)]   # one null on release


def _log(path, flips, lv_fn, freqs=DEFAULT_FREQS):
    log = FrameLog(str(path), chunk=100)       # small chunk exercises growth
    for i, t in enumerate(flips):
        log.add(i + 1, t, t, lv_fn(i, t), freqs)
    assert log.save() == len(flips)


def test_frame_log_roundtrip_and_analyzer_measures_frequencies(tmp_path, capsys):
    rng = np.random.default_rng(0)
    flips = np.cumsum(1 / 120 + rng.normal(0, 0.0003, 1200))
    flips[600:] += 1 / 120                         # one late frame mid-run
    p = tmp_path / "frames.csv"
    _log(p, flips, lambda i, t: levels(DEFAULT_FREQS, t))
    d = analyze.load(str(p))
    assert list(d) == FrameLog.COLUMNS
    tm = analyze.timing(d)
    assert tm["late"] == 1 and 119 < tm["fps"] < 120.1
    assert analyze.main([str(p)]) == 0
    assert "measured 11.00/14.00/17.00/20.00 OK" in capsys.readouterr().out


def test_analyzer_catches_frame_counter_flicker(tmp_path, capsys):
    # A frame-counter flicker that assumes 120 Hz but really flips at 100 Hz
    # runs every target 17% slow: exactly what design rule 1 forbids.
    flips = np.arange(1000) / 100.0
    p = tmp_path / "bad.csv"
    _log(p, flips, lambda i, t: levels(DEFAULT_FREQS, i / 120.0))
    assert analyze.main([str(p)]) == 1
    assert "MISMATCH" in capsys.readouterr().out


def test_analyzer_splits_on_live_frequency_change(tmp_path, capsys):
    flips = np.arange(1200) / 120.0
    log = FrameLog(str(tmp_path / "chg.csv"))
    for i, t in enumerate(flips):
        f = DEFAULT_FREQS if t < 5 else (12.0, 14.0, 17.0, 20.0)
        log.add(i, t, t, levels(f, t), f)
    log.save()
    assert analyze.main([str(tmp_path / "chg.csv")]) == 0
    out = capsys.readouterr().out
    assert "configured 11/14/17/20 -> measured 11.00/14.00/17.00/20.00 OK" in out
    assert "configured 12/14/17/20 -> measured 12.00/14.00/17.00/20.00 OK" in out


def _st(**kw):
    base = {"control_mode": "latch", "latched": None, "latched_at": None, "params": {"latch_max_s": 3.0},
            "clench": {"z": 1.0, "fired_at": None, "count": 0, "ignored_at": None}}
    base.update(kw)
    return base


def test_latch_view_hold_mode_and_missing_fields():
    from hub.gui.logic import LatchView
    v = LatchView()
    # An older hub without Phase 6 fields reads as hold mode, nothing latched.
    out = v.update({"armed": True}, now=0.0, t_hub=100.0)
    assert out["mode"] == "hold" and not out["preview"] and out["latched"] is None and out["frac"] is None
    assert v.update(None, now=0.1, t_hub=None)["mode"] == "hold"


def test_latch_view_preview_latch_timer_and_flash():
    from hub.gui.logic import LatchView
    v = LatchView(flash_s=0.4, no_target_s=1.5)
    out = v.update(_st(), now=10.0, t_hub=100.0)
    assert out["preview"] and not out["flash"] and not out["no_target"]
    # clench latches "up" at t_hub 100.5
    s = _st(latched="up", latched_at=100.5, clench={"z": 20, "fired_at": 100.5, "count": 1})
    out = v.update(s, now=10.6, t_hub=100.6)
    assert out["latched"] == "up" and not out["preview"] and out["flash"]
    assert math.isclose(out["frac"], (3.0 - 0.1) / 3.0) and math.isclose(out["remaining_s"], 2.9)
    assert not v.update(s, now=11.1, t_hub=101.1)["flash"]          # flash is short
    assert v.update(s, now=13.0, t_hub=104.0)["frac"] == 0.0         # clamped at the end


def test_latch_view_no_target_and_stale_events_on_connect():
    from hub.gui.logic import LatchView
    v = LatchView(no_target_s=1.5)
    # First state already carries an old clench: no flash, no "no target".
    old = _st(clench={"z": 1, "fired_at": 50.0, "count": 3, "ignored_at": 50.0})
    out = v.update(old, now=0.0, t_hub=100.0)
    assert not out["flash"] and not out["no_target"]
    # A new ignored clench: "no target" shows for 1.5 s.
    s = _st(clench={"z": 20, "fired_at": 101.0, "count": 4, "ignored_at": 101.0})
    assert v.update(s, now=1.0, t_hub=101.0)["no_target"]
    assert v.update(s, now=2.4, t_hub=102.4)["no_target"]
    assert not v.update(s, now=2.6, t_hub=102.6)["no_target"]
    # An event that is already old when first seen changing (e.g. after a reconnect gap) is skipped.
    s2 = _st(clench={"z": 1, "fired_at": 90.0, "count": 5, "ignored_at": 90.0})
    assert not v.update(s2, now=3.0, t_hub=103.0)["no_target"]
    # "no target" never shows while something is latched.
    s3 = _st(latched="left", latched_at=104.0, clench={"z": 1, "fired_at": 104.0, "count": 6, "ignored_at": 103.9})
    assert not v.update(s3, now=4.0, t_hub=104.0)["no_target"]


def test_latch_view_engine_shape_latch_timer_and_results():
    """The engine's actual fields: latch {left_s, max_s}, clench.last {t, result}."""
    from hub.gui.logic import LatchView
    v = LatchView(no_target_s=1.5)
    v.update(_st(), now=0.0, t_hub=100.0)
    s = _st(t_hub=100.5, latched="right", latch={"elapsed_s": 0.5, "max_s": 3.0, "left_s": 2.5},
            clench={"z": 15, "fired_at": 100.0, "count": 1, "last": {"t": 100.0, "result": "latched",
                                                                   "direction": "right"}})
    out = v.update(s, now=0.55, t_hub=100.55)
    assert out["latched"] == "right" and out["flash"] and out["notice"] is None
    # Interpolated between states: 0.05 s after the state, 2.45 s left.
    assert math.isclose(out["remaining_s"], 2.45) and math.isclose(out["frac"], 2.45 / 3.0)
    for result in ("no_target", "not_armed"):
        t = 102.0 if result == "no_target" else 104.0
        s = _st(t_hub=t, clench={"z": 15, "fired_at": t, "count": 2,
                                 "last": {"t": t, "result": result, "direction": None}})
        out = v.update(s, now=t - 100, t_hub=t)
        assert out["notice"] == result and out["flash"] and out["latched"] is None
    # unlatched / hold_mode results flash but carry no notice
    s = _st(t_hub=106.0, clench={"z": 15, "fired_at": 106.0, "count": 3,
                                 "last": {"t": 106.0, "result": "unlatched", "direction": "up"}})
    out = v.update(s, now=7.0, t_hub=106.0)       # the not_armed notice (from now=4) has expired
    assert out["flash"] and out["notice"] is None
