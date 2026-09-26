"""ClenchDetector on synthetic EMG vs EEG, mains, DC offsets, blinks and cable bumps,
plus the recorder round trip on the simulator."""
import os

import numpy as np
import pytest
from scipy.signal import butter, lfilter, sosfilt

from hub.bci.clench import ClenchDetector, run_offline

FS = 250


def eeg(seconds, n_ch=4, seed=0, uv=10.0):
    """Pink-ish background EEG plus 10 Hz alpha, in µV."""
    rng = np.random.default_rng(seed)
    n = int(seconds * FS)
    pink = lfilter([1.0], [1.0, -0.97], rng.standard_normal((n_ch, n)), axis=1) * np.sqrt(1 - 0.97 ** 2)
    t = np.arange(n) / FS
    return uv * (0.7 * pink + 0.5 * rng.standard_normal((n_ch, n))) + 4 * np.sin(2 * np.pi * 10 * t)


def emg(n, n_ch=4, uv=30.0, seed=1):
    sos = butter(4, [30, 110], btype="band", fs=FS, output="sos")
    return uv * sosfilt(sos, np.random.default_rng(seed).standard_normal((n_ch, n)), axis=1) * 2.5


def with_bursts(x, onsets_s, dur_s=0.8, uv=30.0, gains=(1.0, 1.0, 0.9, 0.9)):
    x = x.copy()
    for k, t0 in enumerate(onsets_s):
        s = int(t0 * FS)
        n = int(dur_s * FS)
        x[:, s:s + n] += np.asarray(gains)[:, None] * emg(n, x.shape[0], uv, seed=10 + k)
    return x


def fires_of(x, chunk=12, threshold=8.0):
    _, fires = run_offline(x, FS, threshold=threshold, chunk=chunk)
    return fires


def test_rest_eeg_never_fires():
    assert fires_of(eeg(60)) == []


def test_mains_is_notched():
    x = eeg(40)
    t = np.arange(x.shape[1]) / FS
    # strong mains + 2nd harmonic, whose pickup grows 5x over 0.5 s half way
    # through (someone reaches for the cable). An instant 10x jump in one
    # sample does ring the notch for ~0.1 s and can fire: a known limit.
    gain = np.clip((t - 20.0) / 0.5, 0.0, 1.0) * 4 + 1
    hum = gain * (20 * np.sin(2 * np.pi * 50 * t) + 5 * np.sin(2 * np.pi * 100 * t + 1))
    assert fires_of(x + hum) == []


def test_cyton_dc_offset_does_not_ring():
    offsets = np.array([[-40000.0], [25000.0], [120000.0], [-3000.0]])
    assert fires_of(eeg(20) + offsets) == []


def test_blinks_do_not_fire():
    x = eeg(40)
    for t0 in np.arange(3, 38, 2.3):
        s = int(t0 * FS)
        n = int(0.3 * FS)
        bump = 150 * np.hanning(n)                      # slow, big, frontal
        x[0, s:s + n] += bump
        x[1, s:s + n] += bump
        x[2:, s:s + n] += 0.2 * bump
    assert fires_of(x) == []


def test_single_channel_bump_does_not_fire():
    x = eeg(30)
    for k, t0 in enumerate((5, 12, 20)):
        s = int(t0 * FS)
        x[k % 4, s:] += 300.0                           # electrode pop: a step on one channel
        x[(k + 2) % 4, s + FS] += 400.0                 # a spike on another, 1 s later
    assert fires_of(x) == []


def test_each_clench_fires_once_near_its_onset():
    onsets = [4.0, 7.5, 10.0, 13.3, 17.0, 20.2, 24.0, 27.5, 31.0, 34.4]
    x = with_bursts(eeg(38), onsets)
    fires = fires_of(x)
    assert len(fires) == len(onsets), fires
    for f, t0 in zip(fires, onsets):
        assert 0 <= f / FS - t0 < 0.12, (f / FS, t0)    # ~50 ms minimum + envelope lag


def test_long_clench_fires_once():
    x = with_bursts(eeg(12), [4.0], dur_s=2.5)
    assert len(fires_of(x)) == 1


def test_weak_clench_still_detected_strong_rest_not():
    # a light clench, ~8 µV rms, against 10 µV EEG
    x = with_bursts(eeg(20), [5.0, 10.0, 15.0], uv=8.0)
    assert len(fires_of(x)) == 3


def test_two_quick_clenches_both_fire():
    # clench, release, clench again 0.8 s later: a latch then an unlatch
    x = with_bursts(eeg(12), [4.0, 5.0], dur_s=0.4)
    assert len(fires_of(x)) == 2


def test_chunk_size_does_not_matter():
    x = with_bursts(eeg(20), [5.0, 9.0, 14.0])
    ref = fires_of(x, chunk=12)
    assert fires_of(x, chunk=1) == ref
    assert fires_of(x, chunk=250) == ref


def test_flat_start_does_not_jam_the_detector():
    # Seen live on the Cyton: a flat first second left a baseline spread of ~0,
    # every later sample scored z ~1e11, and nothing fired after the first.
    live = with_bursts(eeg(30), [6.0, 12.0, 18.0, 24.0])
    x = np.concatenate([np.repeat(live[:, :1], 2 * FS, axis=1), live], axis=1)
    det = ClenchDetector(FS, 4)
    fires = []
    for s in range(0, x.shape[1], 125):           # 0.5 s bursts, like the live dongle
        fires += [s + f for f in det.update(x[:, s:s + 125])]
    assert [round(f / FS - 2) for f in fires] == [6, 12, 18, 24]


def test_flat_channels_are_left_out():
    # Fp1 and Fp2 railed (a constant) the whole time: P7/P8 still detect.
    x = with_bursts(eeg(30), [6.0, 12.0, 18.0, 24.0])
    x[:2] = 187500.0
    det = ClenchDetector(FS, 4)
    fires = []
    for s in range(0, x.shape[1], 12):
        fires += det.update(x[:, s:s + 12])
    assert len(fires) == 4
    assert det.flat == [0, 1]
    assert det.z_peak < 1e6


def test_stuck_above_threshold_relearns():
    # A baseline learned from a much quieter signal: z sits far above the
    # threshold. After 3 s the detector re-learns and clenches fire again.
    quiet = eeg(4) * 0.02
    x = np.concatenate([quiet, with_bursts(eeg(20), [10.0, 15.0])], axis=1)
    det = ClenchDetector(FS, 4)
    fires = []
    for s in range(0, x.shape[1], 12):
        fires += [s + f for f in det.update(x[:, s:s + 12])]
    assert det.relearns == 1
    assert [round(f / FS - 4) for f in fires[1:]] == [10, 15]   # the first is the jump itself


def test_threshold_is_live_and_z_reported():
    det = ClenchDetector(FS, 4, threshold=8.0)
    x = with_bursts(eeg(10), [6.0])
    det.update(x[:, :1250])
    assert det.z < 8 and det.count == 0
    det.threshold = 1e6
    assert det.update(x[:, 1250:]) == []
    assert det.z_peak > 50


def test_record_and_analyze_round_trip(tmp_path):
    from hub.bci import record_clench
    out = str(tmp_path / "c.npz")
    record_clench.main(["--device", "sim", "--out", out, "--rest", "1", "--clenches", "2",
                        "--look", "4", "--blink", "1"])
    rec = record_clench.load(out)
    assert rec["fs"] == 250 and rec["ch_names"][:2] == ["Fp1", "Fp2"]
    assert rec["data"].shape[0] == 8 and rec["data"].shape[1] > 250 * 8
    labels = [m[0] for m in rec["markers"]]
    assert labels.count("clench") == 2 and "rest" in labels and "blink" in labels
    for _, s, e in rec["markers"]:
        assert 0 <= s <= e <= rec["data"].shape[1]
    from hub.bci.clench import analyze_recording
    report = analyze_recording(rec)
    assert "suggest threshold" in report
    assert "threshold   8.0: detected 3/3 cues" in report or "detected 4/4 cues" in report, report
    with pytest.raises(SystemExit):
        record_clench.main(["--device", "sim", "--out", out])     # never overwrites
