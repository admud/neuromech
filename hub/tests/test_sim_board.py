"""SimSSVEPBoard fed to the real ssvep_bci.Decoder.

Runs on a fake clock (SimSSVEPBoard's optional `clock`) so a minute of
simulated EEG decodes in a few seconds, with the same 0.25 s decode steps and
overlapping 3 s windows as live.
"""
import collections

import numpy as np
import pytest

import hub.bci  # noqa: F401  (puts control/ on sys.path)
from hub.sim.sim_board import SimSSVEPBoard
from ssvep_bci import Decoder

FREQS = [11.0, 14.0, 17.0, 20.0]
STEP = 0.25


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make(freqs=FREQS, seed=7):
    clock = Clock()
    board = SimSSVEPBoard(freqs, seed=seed, clock=clock)
    board.prepare_session()
    board.start_stream()
    rows = [board.eeg_rows[board.eeg_names.index(n)] for n in ["O1", "O2", "P7", "P8"]]
    dec = Decoder(board, board.sfreq, rows, list(freqs), 3.0, 0.06)
    return clock, board, dec


def run(clock, dec, seconds):
    """Advance time in decode steps; return the winners of every decode."""
    winners = []
    for _ in range(int(round(seconds / STEP))):
        clock.t += STEP
        dec._step(0.0)
        winners.append(dec.state[1])
    return winners


def test_shape_and_history():
    clock, board, _ = make()
    assert board.get_current_board_data(250).shape[1] <= 1     # just started
    clock.t += 2.0
    d = board.get_current_board_data(10000)
    assert d.shape[0] == board.n_rows and 490 <= d.shape[1] <= 510
    counter = d[board.counter_row]
    assert np.all(np.diff(counter) == 1)            # contiguous, newest last
    clock.t += 30.0
    assert board.get_current_board_data(10**6).shape[1] == 2500   # ~10 s kept
    eeg = board.get_current_board_data(2500)[board.eeg_rows]
    assert 5 < eeg.std() < 25                                       # µV scale


def test_stream_stop_freezes_newest_sample():
    clock, board, _ = make()
    clock.t += 1.0
    board.stop_stream()
    a = board.get_current_board_data(1)
    clock.t += 2.0
    assert np.array_equal(a, board.get_current_board_data(1))


def test_each_target_decodes():
    clock, board, dec = make()
    run(clock, dec, 3.0)
    for i in range(4):
        board.set_gaze(i)
        run(clock, dec, 3.0)                 # let the window fill with this target
        winners = run(clock, dec, 10.0)
        acc = np.mean([w == i for w in winners])
        assert acc >= 0.9, (i, collections.Counter(winners))


def test_look_away_mostly_none():
    # ~82% is the decoder's own floor on pure noise at margin 0.06 (see handoff notes).
    clock, board, dec = make()
    board.set_gaze(2)
    run(clock, dec, 5.0)
    board.set_gaze(None)
    run(clock, dec, 3.0)
    winners = run(clock, dec, 60.0)
    rate = np.mean([w is None for w in winners])
    assert rate >= 0.8, collections.Counter(winners)


def test_gaze_change_latency_is_realistic():
    clock, board, dec = make()
    board.set_gaze(0)
    run(clock, dec, 4.0)
    board.set_gaze(3)
    winners = run(clock, dec, 4.0)
    first = next(k for k, w in enumerate(winners) if w == 3)
    # not instant (the window still holds the old target), but within a window
    assert 1 <= first <= 12, winners
    assert winners[0] != 3


def test_set_freqs_respected():
    new = [8.0, 12.5, 15.0, 23.0]
    clock, board, _ = make()
    board.set_freqs(new)
    dec = Decoder(board, board.sfreq, [7, 8, 5, 6], new, 3.0, 0.06)
    board.set_gaze(3)
    run(clock, dec, 3.0)
    winners = run(clock, dec, 5.0)
    assert np.mean([w == 3 for w in winners]) >= 0.9
    # the old 20 Hz decoder no longer sees its target
    old = Decoder(board, board.sfreq, [7, 8, 5, 6], FREQS, 3.0, 0.06)
    old_w = run(clock, old, 5.0)
    assert np.mean([w == 3 for w in old_w]) < 0.3


def test_bad_gaze_index():
    _, board, _ = make()
    with pytest.raises(ValueError):
        board.set_gaze(4)


def test_real_clock_runs():
    board = SimSSVEPBoard(FREQS, seed=1)
    board.start_stream()
    import time
    time.sleep(0.2)
    n = board.get_current_board_data(1000).shape[1]
    assert 30 <= n <= 80
