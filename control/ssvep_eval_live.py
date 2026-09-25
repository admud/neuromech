"""Evaluate SSVEP decoders the way the hub drives the robot.

    python ssvep_eval_live.py calib_s1.npz
    python ssvep_eval_live.py calib_s1.npz --notch 0        # no mains notch, as the decoder was

ssvep_eval.py scores one window per trial, starting exactly at flicker onset.
Live decoding is different: a window slides every 0.25 s, the user switches
gaze from one target to another, and a direction only drives the robot once
it has won by `margin` for `dwell` decodes in a row. This script replays that:

  - Leave-one-block-out. For each held-out block its trials are joined in the
    order they were recorded, which stands in for the user switching gaze
    from target to target (the cue/rest gap between trials isn't recorded,
    so switches here are instant).
  - A window of `--window` seconds slides along that stream in `--step`
    steps. Each window is scored by each decoder; `trca_cca` is fitted on
    the other blocks' trials exactly as the hub fits `--model`.
  - The hub's rules turn scores into a command: winner if it beats the
    runner-up by `margin`, active after `dwell` consecutive wins, dropped
    at once otherwise.

Reported per decoder and margin, as a share of all decode steps:
  correct  the robot moves towards the target the user is looking at
  WRONG    the robot moves somewhere else (the number that matters most)
  idle     no command (safe, but the robot doesn't respond)
  switch   median seconds from a gaze switch to the first correct command
"""
import argparse
import sys

import numpy as np
from scipy.signal import filtfilt, iirnotch

from ssvep_trca import FilterBankTRCA, load_calibration

DIRECTIONS = ["up", "down", "left", "right"]


def notch(x, mains, fs):
    """Remove mains and its first harmonic (zero-phase)."""
    for f0 in (mains, 2 * mains):
        if f0 < fs / 2:
            b, a = iirnotch(f0, 30, fs)
            x = filtfilt(b, a, x, axis=-1)
    return x


def commands(scores, margin, dwell):
    """Hub rules: margin-gated winner per decode, then dwell. -1 = no command."""
    order = np.argsort(scores, axis=1)[:, ::-1]
    top = scores[np.arange(len(scores)), order[:, 0]]
    second = scores[np.arange(len(scores)), order[:, 1]]
    winner = np.where(top - second >= margin, order[:, 0], -1)
    out = np.full(len(winner), -1)
    cand, count = -1, 0
    for i, w in enumerate(winner):
        if w < 0:
            cand, count = -1, 0
        elif w == cand:
            count += 1
        else:
            cand, count = w, 1
        out[i] = cand if cand >= 0 and count >= dwell else -1
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("calib")
    ap.add_argument("--window", type=float, default=3.0, help="decode window, s (hub default 3)")
    ap.add_argument("--step", type=float, default=0.25, help="decode interval, s (hub: 0.25)")
    ap.add_argument("--dwell", type=int, default=2, help="consecutive wins before moving (hub: 2)")
    ap.add_argument("--margins", default="0.02,0.04,0.06,0.08,0.10,0.12")
    ap.add_argument("--notch", type=float, default=50.0,
                    help="mains frequency to notch out (Singapore 50); 0 = off")
    ap.add_argument("--fmax", type=float, default=45.0,
                    help="upper edge of the filter-bank bands, Hz (decoder used 50)")
    args = ap.parse_args()

    d = load_calibration(args.calib)
    epochs, labels, freqs, fs = d["epochs"].astype(float), d["labels"], d["freqs"], d["fs"]
    if args.notch > 0:
        epochs = notch(epochs, args.notch, fs)
    bands = [(6, args.fmax), (14, args.fmax), (22, args.fmax)]
    n_win, n_step = int(args.window * fs), int(args.step * fs)
    n_trial = epochs.shape[2]
    margins = [float(m) for m in args.margins.split(",")]

    block = np.zeros(len(labels), dtype=int)
    for k in range(len(freqs)):
        idx = np.where(labels == k)[0]
        block[idx] = np.arange(len(idx))
    n_blocks = block.max() + 1

    print("%s: %d trials, %s, %.0f s each, %d blocks" % (
        args.calib, len(labels), ", ".join(d["ch_names"]), d["trial_len"], n_blocks))
    print("window %.1f s, step %.2f s, dwell %d, notch %s, bands to %g Hz\n" % (
        args.window, args.step, args.dwell, "%g Hz" % args.notch if args.notch else "off", args.fmax))

    # Scores for every decode step of every held-out stream, per decoder.
    runs = {"cca": [], "trca_cca": []}
    for b in range(n_blocks):
        test = np.where(block == b)[0]            # recording order
        train = block != b
        model = FilterBankTRCA(freqs, fs, bands=bands)
        model.fit(epochs[train][:, :, :n_win], labels[train])
        stream = np.concatenate([epochs[i] for i in test], axis=1)
        truth = np.repeat(labels[test], n_trial)  # target shown at each sample
        ends = np.arange(n_win, stream.shape[1] + 1, n_step)
        for mode in runs:
            sc = np.array([model.score(stream[:, e - n_win:e], mode=mode) for e in ends])
            runs[mode].append((sc, truth[ends - 1], ends))

    for mode, parts in runs.items():
        print("%s" % mode)
        print("  margin   correct   WRONG    idle   switch")
        for m in margins:
            cor = wro = idl = tot = 0
            lat = []
            for sc, truth, ends in parts:
                cmd = commands(sc, m, args.dwell)
                cor += int(np.sum(cmd == truth))
                wro += int(np.sum((cmd >= 0) & (cmd != truth)))
                idl += int(np.sum(cmd < 0))
                tot += len(cmd)
                # gaze switches happen at trial boundaries inside the stream
                for s in range(n_trial, ends[-1], n_trial):
                    after = np.where((ends > s) & (cmd == truth))[0]
                    if len(after):
                        lat.append((ends[after[0]] - s) / fs)
            sw = "%.2f s" % np.median(lat) if lat else "never"
            print("  %5.2f   %6.0f%%  %6.0f%%  %6.0f%%   %s" % (
                m, 100 * cor / tot, 100 * wro / tot, 100 * idl / tot, sw))
        print()
    print("Chance for 'correct' with no margin is ~25%. Prefer the row with low WRONG and")
    print("reasonable correct; a model is only worth using if it beats cca at similar WRONG.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
