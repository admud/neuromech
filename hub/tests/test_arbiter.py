"""Arbiter: dwell, look-away, override, arming, velocity signs."""
import pytest

from hub.bci.arbiter import OVERRIDE_TTL_S, Arbiter, velocity

T = 100.0  # an arbitrary "now"


def armed_cmd(a, now=T, eeg_ok=True):
    return a.command(armed=True, eeg_ok=eeg_ok, now=now)


def test_direction_velocity_signs():
    # ROS axes: vx forward+, vy left+.
    assert velocity("up", 0.3) == (0.3, 0.0)
    assert velocity("down", 0.3) == (-0.3, 0.0)
    assert velocity("left", 0.3) == (0.0, 0.3)
    assert velocity("right", 0.3) == (0.0, -0.3)
    assert velocity(None, 0.3) == (0.0, 0.0)


def test_dwell_activation():
    a = Arbiter(dwell=3, speed=0.4)
    a.on_decode("up")
    a.on_decode("up")
    assert armed_cmd(a)["direction"] is None
    assert a.dwell_status() == {"direction": "up", "count": 2, "needed": 3}
    a.on_decode("up")
    c = armed_cmd(a)
    assert c == {"vx": 0.4, "vy": 0.0, "direction": "up", "source": "bci"}
    a.on_decode("up")
    assert a.dwell_status()["count"] == 3  # capped at needed


def test_dwell_1_is_immediate():
    a = Arbiter(dwell=1)
    a.on_decode("right")
    assert armed_cmd(a)["vy"] == -0.3


def test_look_away_releases_immediately():
    a = Arbiter(dwell=2)
    for _ in range(5):
        a.on_decode("left")
    assert armed_cmd(a)["direction"] == "left"
    a.on_decode(None)
    c = armed_cmd(a)
    assert (c["vx"], c["vy"], c["direction"], c["source"]) == (0.0, 0.0, None, "none")
    # and it must dwell again
    a.on_decode("left")
    assert armed_cmd(a)["direction"] is None
    a.on_decode("left")
    assert armed_cmd(a)["direction"] == "left"


def test_different_winner_releases_and_redwells():
    a = Arbiter(dwell=2)
    a.on_decode("up")
    a.on_decode("up")
    assert armed_cmd(a)["direction"] == "up"
    a.on_decode("down")
    assert armed_cmd(a)["direction"] is None
    assert a.dwell_status() == {"direction": "down", "count": 1, "needed": 2}
    a.on_decode("down")
    assert armed_cmd(a)["vx"] == -0.3


def test_interleaved_winners_never_activate():
    a = Arbiter(dwell=2)
    for w in ["up", "down", "up", None, "up", "left"]:
        a.on_decode(w)
        assert armed_cmd(a)["direction"] is None


def test_disarmed_is_zero_even_with_dwell_and_override():
    a = Arbiter(dwell=1)
    a.on_decode("up")
    a.set_override("left", T)
    c = a.command(armed=False, eeg_ok=True, now=T)
    assert c == {"vx": 0.0, "vy": 0.0, "direction": None, "source": "none"}


def test_override_beats_bci_and_expires():
    a = Arbiter(dwell=1)
    a.on_decode("up")
    a.set_override("right", T)
    c = armed_cmd(a, T + 0.1)
    assert (c["direction"], c["source"], c["vy"]) == ("right", "override", -0.3)
    # still live just before the TTL, gone after it; BCI takes back over
    assert armed_cmd(a, T + OVERRIDE_TTL_S - 0.01)["source"] == "override"
    assert OVERRIDE_TTL_S == 0.5
    c = armed_cmd(a, T + OVERRIDE_TTL_S + 0.01)
    assert (c["direction"], c["source"]) == ("up", "bci")


def test_override_refresh_and_clear():
    a = Arbiter()
    a.set_override("down", T)
    a.set_override("down", T + 0.4)  # resent while the key is held
    assert armed_cmd(a, T + 0.8)["source"] == "override"
    a.set_override(None, T + 0.85)
    assert armed_cmd(a, T + 0.86)["source"] == "none"


def test_override_works_without_eeg_but_bci_does_not():
    a = Arbiter(dwell=1)
    a.on_decode("up")
    assert armed_cmd(a, eeg_ok=False)["direction"] is None
    a.set_override("left", T)
    assert armed_cmd(a, eeg_ok=False)["direction"] == "left"


def test_bad_direction_rejected():
    a = Arbiter()
    with pytest.raises(ValueError):
        a.on_decode("forward")
    with pytest.raises(ValueError):
        a.set_override("spin", T)


# ---- Phase 6: latch mode -------------------------------------------------

def latch_arbiter(**kw):
    a = Arbiter(dwell=2, speed=0.3, mode="latch", **kw)
    return a


def dwell_on(a, d, t0, n=3, step=0.25):
    """n decodes of `d`, 0.25 s apart, ending at t0 + (n-1)*step. Returns that time."""
    for k in range(n):
        a.on_decode(d, t0 + k * step)
    return t0 + (n - 1) * step


def test_hold_mode_ignores_clench():
    a = Arbiter(dwell=1)
    a.on_decode("up", T)
    assert a.clench(T + 0.1, T + 0.15) == ("hold_mode", None)
    assert a.latched is None


def test_latch_mode_gaze_only_previews():
    a = latch_arbiter()
    t = dwell_on(a, "up", T)
    assert a.active == "up"
    assert armed_cmd(a, t)["direction"] is None           # preview: no motion
    assert a.dwell_status()["direction"] == "up"


def test_clench_latches_last_dwelled_winner_and_gaze_is_free():
    a = latch_arbiter()
    t = dwell_on(a, "left", T)
    assert a.clench(onset=t + 0.1, now=t + 0.2) == ("latched", "left")
    c = armed_cmd(a, t + 0.3)
    assert (c["direction"], c["vy"], c["source"]) == ("left", 0.3, "bci")
    for k, w in enumerate(["up", None, "right", "right", "right"]):   # gaze wanders
        a.on_decode(w, t + 0.5 + 0.25 * k)
    assert armed_cmd(a, t + 2.0)["direction"] == "left"


def test_clench_ignores_decodes_after_its_onset():
    # The only dwelled decode is after the onset (EMG in its window): no target.
    a = latch_arbiter()
    a.on_decode("up", T)
    a.on_decode("up", T + 0.3)                              # dwelled at T+0.3
    assert a.clench(onset=T + 0.2, now=T + 0.35) == ("no_target", None)


def test_clench_looks_back_only_half_a_second():
    a = latch_arbiter()
    t = dwell_on(a, "up", T)
    a.on_decode(None, t + 0.25)
    a.on_decode(None, t + 0.5)
    assert a.clench(onset=t + 0.6, now=t + 0.7) == ("no_target", None)   # last active 0.6 s ago
    a2 = latch_arbiter()
    t = dwell_on(a2, "up", T)
    a2.on_decode(None, t + 0.25)
    assert a2.clench(onset=t + 0.4, now=t + 0.5) == ("latched", "up")    # 0.4 s ago: ok


def test_clench_with_no_winner_is_ignored():
    a = latch_arbiter()
    a.on_decode("up", T)                                     # never dwelled
    assert a.clench(T + 0.1, T + 0.2) == ("no_target", None)
    assert armed_cmd(a, T + 0.3)["direction"] is None


def test_second_clench_always_stops_even_looking_elsewhere():
    a = latch_arbiter()
    t = dwell_on(a, "up", T)
    a.clench(t + 0.1, t + 0.2)
    t2 = dwell_on(a, "down", t + 0.5)                        # now dwelling on another target
    assert a.clench(t2 + 0.1, t2 + 0.2) == ("unlatched", "up")
    assert armed_cmd(a, t2 + 0.3)["direction"] is None


def test_latch_expires_after_latch_max():
    a = latch_arbiter(latch_max_s=3.0)
    t = dwell_on(a, "right", T)
    a.clench(t + 0.1, t + 0.2)
    assert a.latch_status(t + 1.2) == {"elapsed_s": 1.0, "max_s": 3.0, "left_s": 2.0}
    assert armed_cmd(a, t + 3.1)["direction"] == "right"
    assert armed_cmd(a, t + 3.25)["direction"] is None      # 3.05 s after latching
    assert a.latched is None and a.latch_status(t + 3.3) is None


def test_expire_reports_once():
    a = latch_arbiter(latch_max_s=1.0)
    t = dwell_on(a, "up", T)
    a.clench(t, t)
    assert a.expire(t + 0.5) is False
    assert a.expire(t + 1.0) is True
    assert a.expire(t + 1.5) is False


def test_override_beats_latch_then_latch_resumes():
    a = latch_arbiter(latch_max_s=5.0)
    t = dwell_on(a, "up", T)
    a.clench(t, t)
    a.set_override("left", t + 0.5)
    assert armed_cmd(a, t + 0.6)["source"] == "override"
    assert armed_cmd(a, t + 1.2)["direction"] == "up"


def test_latched_but_disarmed_or_eeg_bad_is_zero():
    a = latch_arbiter()
    t = dwell_on(a, "up", T)
    a.clench(t, t)
    assert a.command(armed=False, eeg_ok=True, now=t + 0.1)["direction"] is None
    assert armed_cmd(a, t + 0.1, eeg_ok=False)["direction"] is None


def test_unknown_mode_rejected():
    with pytest.raises(ValueError):
        Arbiter(mode="toggle")
