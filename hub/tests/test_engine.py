"""BciEngine: interface shape, validation, safety rules, sim end-to-end, port detection."""
import builtins
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from hub.bci import board as boardmod
from hub.bci.config import EngineSettings
from hub.bci.engine import BciEngine, SeqDecoder

ENGINE_KEYS = {"armed", "disarm_reason", "winner", "scores", "command", "dwell",
               "decode_ms", "params", "eeg", "sim", "warnings"}


def wait_for(pred, timeout, step=0.05):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(step)
    return pred()


@pytest.fixture
def sim_engine():
    e = BciEngine(EngineSettings(device="sim"))
    e.settle_s = 0.2
    e.start()
    yield e
    e.stop()


def arm(e, source="dashboard"):
    e.handle({"type": "arm", "armed": True}, source)
    return e.status()["armed"]


# ---- lifecycle and shape -------------------------------------------------

def test_synthetic_start_stop_and_status_shape():
    e = BciEngine(EngineSettings(device="synthetic"))
    e.settle_s = 0.2
    st = e.status()
    assert st["armed"] is False and st["disarm_reason"] == "startup"
    assert st["eeg"]["ok"] is False          # not started yet
    e.start()
    try:
        assert wait_for(lambda: e.status()["decode_ms"] > 0, 6.0)
        st = e.status()
        assert set(st) == ENGINE_KEYS
        assert list(st["scores"]) == ["up", "down", "left", "right"]
        assert set(st["command"]) == {"vx", "vy", "direction", "source"}
        assert set(st["dwell"]) == {"direction", "count", "needed"}
        assert st["params"] == {"window_s": 3.0, "margin": 0.08, "dwell": 2, "speed": 0.3}
        eeg = st["eeg"]
        assert eeg["device"] == "synthetic" and eeg["fs"] == 250 and eeg["ok"] is True
        assert len(eeg["channels"]) == 4 and eeg["stalled_s"] < 1.0
        assert st["sim"] is None
        assert any("synthetic board" in w for w in st["warnings"])
        assert st["winner"] in (None, "up", "down", "left", "right")
        assert wait_for(lambda: len(e.status()["eeg"]["quality"]) == 4, 2.0)
        q = e.status()["eeg"]["quality"][0]
        assert set(q) == {"name", "std_uv", "railed"}
        cfg = e.config_message()
        assert cfg["type"] == "config" and isinstance(cfg["config_id"], int)
        assert cfg["targets"] == [{"id": "up", "freq": 11.0}, {"id": "down", "freq": 14.0},
                                  {"id": "left", "freq": 17.0}, {"id": "right", "freq": 20.0}]
    finally:
        e.stop()


def test_public_methods_are_fast(sim_engine):
    e = sim_engine
    arm(e)
    calls = [e.status, e.command, e.config_message,
             lambda: e.handle({"type": "override", "direction": "up"}, "dashboard"),
             lambda: e.set_phone_connected(False)]
    for fn in calls:
        t0 = time.perf_counter()
        for _ in range(200):
            fn()
        assert (time.perf_counter() - t0) / 200 < 1e-3, fn


def test_concurrent_calls_do_not_break(sim_engine):
    e = sim_engine
    errors = []

    def hammer(fn):
        try:
            for _ in range(300):
                fn()
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    fns = [e.status, e.command,
           lambda: e.handle({"type": "sim_gaze", "target": "up"}, "dashboard"),
           lambda: e.handle({"type": "set_config", "dwell": 3}, "dashboard"),
           lambda: e.handle({"type": "arm", "armed": True}, "phone")]
    ts = [threading.Thread(target=hammer, args=(f,)) for f in fns]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors


# ---- handle() and validation ---------------------------------------------

def test_set_config_validation(sim_engine):
    e = sim_engine
    before = e.status()["params"], e.config_message()
    bad = [
        {"freqs": {"up": 4.0}},                  # below 5 Hz
        {"freqs": {"up": 41.0}},                 # above 40 Hz
        {"freqs": {"up": 14.0}},                 # clashes with down: not distinct
        {"freqs": {"forward": 12.0}},
        {"freqs": {"up": "x"}},
        {"window_s": 0.4}, {"window_s": 7}, {"margin": -0.1}, {"margin": 1.5},
        {"dwell": 0}, {"dwell": 11}, {"dwell": 2.5}, {"speed": 1.2}, {"speed": True},
        {"window_s": 2.0, "dwell": 99},          # one bad field rejects the lot
    ]
    for body in bad:
        assert e.handle({"type": "set_config", **body}, "dashboard") is False, body
        assert (e.status()["params"], e.config_message()) == before, body


def test_set_config_applies(sim_engine):
    e = sim_engine
    cid = e.config_message()["config_id"]
    assert e.handle({"type": "set_config", "dwell": 3, "speed": 0.5, "window_s": 2.0,
                     "margin": 0.08}, "dashboard") is False  # freqs unchanged
    assert e.status()["params"] == {"window_s": 2.0, "margin": 0.08, "dwell": 3, "speed": 0.5}
    assert e.status()["dwell"]["needed"] == 3
    assert e.config_message()["config_id"] == cid
    # freqs change: True, new config_id, sim board follows, same freqs again: False
    assert e.handle({"type": "set_config", "freqs": {"up": 12.0}}, "dashboard") is True
    cfg = e.config_message()
    assert cfg["config_id"] == cid + 1 and cfg["targets"][0] == {"id": "up", "freq": 12.0}
    assert e._ob.board._freqs == [12.0, 14.0, 17.0, 20.0]
    assert e.handle({"type": "set_config", "freqs": {"up": 12.0}}, "dashboard") is False
    # the decoder is rebuilt with the new settings
    assert wait_for(lambda: not e._rebuild and e._decoder.freqs[0] == 12.0
                    and e._decoder.n_samples == 500, 2.0)


def test_set_config_warnings(sim_engine):
    e = sim_engine
    assert e.status()["warnings"] == []
    e.handle({"type": "set_config", "freqs": {"up": 10.0, "left": 20.0, "right": 30.0}},
             "dashboard")
    w = " ".join(e.status()["warnings"])
    assert "share a harmonic" in w


def test_sources_are_enforced(sim_engine):
    e = sim_engine
    # the phone can arm and STOP, nothing else
    assert arm(e, "phone")
    e.handle({"type": "override", "direction": "up"}, "phone")
    assert e.command()["source"] != "override"
    e.handle({"type": "sim_gaze", "target": "up"}, "phone")
    assert e.status()["sim"] == {"gaze": None}
    assert e.handle({"type": "set_config", "freqs": {"up": 12.0}}, "phone") is False
    assert e.config_message()["targets"][0]["freq"] == 11.0
    # unknown types and garbage are ignored
    assert e.handle({"type": "nope"}, "dashboard") is False
    assert e.handle({"type": "arm", "armed": "yes"}, "dashboard") is False
    assert e.handle({"type": "override", "direction": "spin"}, "dashboard") is False
    assert e.status()["armed"] is True
    e.handle({"type": "arm", "armed": False}, "phone")
    st = e.status()
    assert st["armed"] is False and st["disarm_reason"] == "user"


def test_sim_gaze_only_with_sim_device():
    e = BciEngine(EngineSettings(device="synthetic"))
    e.handle({"type": "sim_gaze", "target": "up"}, "dashboard")
    assert e.status()["sim"] is None


# ---- safety model --------------------------------------------------------

def test_starts_disarmed_and_arm_refused_without_eeg():
    e = BciEngine(EngineSettings(device="sim"))
    assert e.status()["armed"] is False
    assert e.status()["disarm_reason"] == "startup"
    assert not arm(e)                      # not started: EEG not ok
    assert e.command() == {"vx": 0.0, "vy": 0.0, "direction": None, "source": "none"}


def test_no_phone_needed_to_arm(sim_engine):
    assert arm(sim_engine, "dashboard")


def test_phone_lost_disarms(sim_engine):
    e = sim_engine
    e.set_phone_connected(True)
    assert arm(e, "phone")
    e.set_phone_connected(True)            # repeated True is harmless
    assert e.status()["armed"]
    e.set_phone_connected(False)
    st = e.status()
    assert st["armed"] is False and st["disarm_reason"] == "phone_lost"
    # re-arming is explicit, and works from the dashboard with no phone
    assert arm(e)
    assert e.status()["disarm_reason"] is None


def test_robot_lost_disarms(sim_engine):
    e = sim_engine
    e.set_robot_connected(True)
    assert arm(e)
    e.set_robot_connected(False)
    st = e.status()
    assert st["armed"] is False and st["disarm_reason"] == "robot_lost"
    # a robot dropping while disarmed doesn't overwrite the reason
    e.handle({"type": "arm", "armed": False}, "dashboard")
    e.set_robot_connected(True)
    e.set_robot_connected(False)
    assert e.status()["disarm_reason"] == "user"


def test_eeg_stall_disarms_and_blocks_arming(sim_engine):
    e = sim_engine
    assert arm(e)
    e._ob.board.stop_stream()              # newest sample freezes
    assert wait_for(lambda: not e.status()["armed"], 3.0)
    st = e.status()
    assert st["disarm_reason"] == "eeg_stall" and st["eeg"]["ok"] is False
    assert st["eeg"]["stalled_s"] > 1.5
    assert not arm(e)
    # override still needs armed
    e.handle({"type": "override", "direction": "up"}, "dashboard")
    assert e.command()["direction"] is None


def test_override_needs_armed_and_expires(sim_engine):
    e = sim_engine
    e.handle({"type": "override", "direction": "left"}, "dashboard")
    assert arm(e)
    assert e.command()["source"] == "none"          # pre-arm key press didn't stick
    e.handle({"type": "override", "direction": "left"}, "dashboard")
    c = e.command()
    assert (c["direction"], c["source"], c["vy"]) == ("left", "override", 0.3)
    time.sleep(0.6)
    assert e.command()["source"] != "override"
    e.handle({"type": "override", "direction": "down"}, "dashboard")
    e.handle({"type": "arm", "armed": False}, "dashboard")
    assert e.command() == {"vx": 0.0, "vy": 0.0, "direction": None, "source": "none"}


def test_disarmed_command_is_zero_while_gazing(sim_engine):
    e = sim_engine
    e.handle({"type": "sim_gaze", "target": "up"}, "dashboard")
    assert wait_for(lambda: e.status()["dwell"]["count"] >= 2, 6.0)
    assert e.command() == {"vx": 0.0, "vy": 0.0, "direction": None, "source": "none"}


def test_stale_decodes_do_not_keep_moving(sim_engine):
    e = sim_engine
    e.handle({"type": "sim_gaze", "target": "up"}, "dashboard")
    assert arm(e)
    assert wait_for(lambda: e.command()["direction"] == "up", 6.0)
    e._decoder.stop()                      # decoder dies; EEG keeps flowing
    assert wait_for(lambda: e.command()["direction"] is None, 2.5)


# ---- end to end on the simulator -----------------------------------------

def test_sim_gaze_drives_and_look_away_stops(sim_engine):
    e = sim_engine
    assert arm(e)
    e.handle({"type": "sim_gaze", "target": "left"}, "dashboard")
    assert e.status()["sim"] == {"gaze": "left"}
    assert wait_for(lambda: e.command()["direction"] == "left", 5.0)
    c = e.command()
    assert c["vy"] > 0 and c["vx"] == 0 and c["source"] == "bci"
    e.handle({"type": "sim_gaze", "target": None}, "dashboard")
    assert wait_for(lambda: e.command()["direction"] is None, 4.0)
    c = e.command()
    assert (c["vx"], c["vy"]) == (0.0, 0.0)


def test_sim_signs_all_directions(sim_engine):
    e = sim_engine
    assert arm(e)
    expect = {"up": (1, 0), "down": (-1, 0), "right": (0, -1)}
    for target, (sx, sy) in expect.items():
        e.handle({"type": "sim_gaze", "target": target}, "dashboard")
        assert wait_for(lambda: e.command()["direction"] == target, 6.0), target
        c = e.command()
        assert np.sign(c["vx"]) == sx and np.sign(c["vy"]) == sy


# ---- decoder wrapper -----------------------------------------------------

def test_each_decode_counted_once():
    class Board:
        def __init__(self):
            self.n = 100

        def get_current_board_data(self, n):
            return np.random.default_rng(0).standard_normal((9, min(n, self.n)))

    b = Board()
    got = []
    dec = SeqDecoder(b, 250, [1, 2, 3, 4], [11, 14, 17, 20], 1.0, 0.06,
                     on_decode=lambda s, w, ms: got.append(w))
    dec._step(0.0)                          # buffer still filling: no decode
    assert dec.seq == 0 and got == []
    b.n = 10**6
    for k in range(3):
        dec._step(0.0)
    assert dec.seq == 3 and len(got) == 3


# ---- port detection and the cyton path -----------------------------------

def port(dev, vid=None, pid=None, desc="", hwid=""):
    return SimpleNamespace(device=dev, vid=vid, pid=pid, description=desc, hwid=hwid,
                           manufacturer=None)


BT = [port("COM3", desc="Standard Serial over Bluetooth link (COM3)", hwid="BTHENUM\\{...}"),
      port("COM4", desc="Standard Serial over Bluetooth link (COM4)", hwid="BTHENUM\\{...}")]


def test_find_port_single_dongle():
    ports = BT + [port("COM8", 0x0403, 0x6015, "USB Serial Port (COM8)")]
    assert boardmod.find_openbci_port(ports) == "COM8"


def test_find_port_prefers_exact_pid():
    ports = [port("COM5", 0x0403, 0x6001, "USB Serial Port"),
             port("COM6", 0x0403, 0x6015, "USB Serial Port")]
    assert boardmod.find_openbci_port(ports) == "COM6"


def test_find_port_none_lists_ports():
    with pytest.raises(boardmod.BoardError) as ei:
        boardmod.find_openbci_port(BT)
    msg = str(ei.value)
    assert "COM3" in msg and "COM4" in msg and "--port" in msg


def test_find_port_empty():
    with pytest.raises(boardmod.BoardError, match="--port"):
        boardmod.find_openbci_port([])


def test_find_port_several():
    ports = [port("COM6", 0x0403, 0x6015), port("COM9", 0x0403, 0x6015)]
    with pytest.raises(boardmod.BoardError) as ei:
        boardmod.find_openbci_port(ports)
    assert "COM6" in str(ei.value) and "COM9" in str(ei.value)


def test_find_port_ignores_ftdi_looking_bluetooth():
    ports = [port("COM3", 0x0403, 0x6015, "Standard Serial over Bluetooth link")]
    with pytest.raises(boardmod.BoardError):
        boardmod.find_openbci_port(ports)


def test_cyton_without_dongle_fails_fast(monkeypatch):
    from serial.tools import list_ports
    monkeypatch.setattr(list_ports, "comports", lambda: list(BT))

    def no_input(*a, **k):
        raise AssertionError("input() must never be called")
    monkeypatch.setattr(builtins, "input", no_input)
    e = BciEngine(EngineSettings(device="cyton"))
    t0 = time.monotonic()
    with pytest.raises(boardmod.BoardError, match="--port"):
        e.start()
    assert time.monotonic() - t0 < 2.0


def test_cyton_bad_port_fails_fast(monkeypatch):
    def no_input(*a, **k):
        raise AssertionError("input() must never be called")
    monkeypatch.setattr(builtins, "input", no_input)
    e = BciEngine(EngineSettings(device="cyton", port="COM99"))
    with pytest.raises(boardmod.BoardError, match="COM99"):
        e.start()


def test_unknown_device():
    with pytest.raises(boardmod.BoardError):
        BciEngine(EngineSettings(device="muse")).start()


def test_frozen_process_disarms_on_resume(sim_engine):
    # A frozen hub (e.g. suspended) must not come back armed, even though the
    # board catches up and the newest sample looks fresh again.
    e = sim_engine
    assert arm(e)
    e._running = False                      # stop the loop, as if the process froze
    e._loop_thread.join(timeout=1.0)
    time.sleep(1.7)
    e._last_change_t = time.monotonic()     # board caught up before any status() call
    e._running = True
    e._loop_thread = threading.Thread(target=e._loop, daemon=True)
    e._loop_thread.start()
    assert wait_for(lambda: not e.status()["armed"], 1.0)
    assert e.status()["disarm_reason"] == "eeg_stall"
