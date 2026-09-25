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
