"""Compare SSVEP decoders on your own calibration data.

    python ssvep_eval.py calib_s1.npz

Leave-one-block-out cross-validation of three decoders at several window
lengths, so you can see whether calibration actually bought you anything and
which decode window to run the BCI at.

  cca       no training (what ssvep_bci.py uses by default)
  trca_cca  learned spatial filter, phase-invariant frequency match
  trca      full ensemble TRCA with individual templates

Also reports information transfer rate, which is the number that matters for
control: accuracy alone ignores how long each decision took.
"""
import argparse
import sys

import numpy as np

from ssvep_trca import FilterBankTRCA, load_calibration

MODES = ["cca", "trca_cca", "trca"]


def itr_bpm(accuracy, n_classes, seconds_per_selection):
    """Wolpaw information transfer rate, bits per minute."""
    p, n = accuracy, n_classes
    if p <= 1.0 / n:
        return 0.0
    if p >= 1.0:
        bits = np.log2(n)
    else:
        bits = (np.log2(n) + p * np.log2(p) + (1 - p) * np.log2((1 - p) / (n - 1)))
    return float(bits * 60.0 / seconds_per_selection)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("calib", help="npz from ssvep_calibrate.py")
    ap.add_argument("--windows", default="1.0,1.5,2.0,3.0,4.0",
                    help="decode window lengths to evaluate, seconds")
    ap.add_argument("--overhead", type=float, default=0.5,
                    help="seconds of gaze-shift/settle time added per selection for ITR")
    args = ap.parse_args()

    d = load_calibration(args.calib)
    epochs, labels = d["epochs"], d["labels"]
    freqs, fs = d["freqs"], d["fs"]
    n_trials, n_ch, n_samp = epochs.shape
    n_classes = len(freqs)

    print("%s" % args.calib)
    print("  %d trials, %d channels (%s), %d Hz, %.1f s per trial"
          % (n_trials, n_ch, ", ".join(d["ch_names"]), fs, d["trial_len"]))
    print("  targets: %s Hz" % ", ".join("%g" % f for f in freqs))
    counts = np.bincount(labels, minlength=n_classes)
    print("  trials per target: %s" % counts.tolist())
    if counts.min() < 2:
        print("\n  ! at least 2 trials per target are needed to fit TRCA")
        return 1

    # Blocks: the k-th occurrence of each label forms one fold, matching how
    # ssvep_calibrate.py interleaves targets.
    block_id = np.zeros(n_trials, dtype=int)
    for k in range(n_classes):
        idx = np.where(labels == k)[0]
        block_id[idx] = np.arange(len(idx))
    n_blocks = int(block_id.max()) + 1
    if n_blocks < 2:
        print("\n  ! need at least 2 blocks for cross-validation")
        return 1
    print("  %d blocks -> leave-one-block-out CV\n" % n_blocks)

    windows = [float(x) for x in args.windows.split(",")]
    windows = [w for w in windows if int(w * fs) <= n_samp]

    results = {m: {} for m in MODES}
    for win in windows:
        n = int(win * fs)
        for mode in MODES:
            correct = total = 0
            for b in range(n_blocks):
                tr = block_id != b
                te = block_id == b
                if tr.sum() == 0 or te.sum() == 0:
                    continue
                model = FilterBankTRCA(freqs, fs)
                if mode != "cca":
                    model.fit(epochs[tr][:, :, :n], labels[tr])
                for x, y in zip(epochs[te], labels[te]):
                    pred = model.predict(x[:, :n], mode=mode)
                    correct += int(pred == y)
                    total += 1
            results[mode][win] = correct / max(total, 1)

    print(f"{'window':>8}" + "".join(f"{m:>11}" for m in MODES))
    print("-" * (8 + 11 * len(MODES)))
    for win in windows:
        print(f"{win:7.1f}s" + "".join(f"{results[m][win]:10.0%} " for m in MODES))
    print("\nchance = %.0f%%" % (100.0 / n_classes))

    print("\nInformation transfer rate (bits/min, +%.1fs overhead per selection):"
          % args.overhead)
    print(f"{'window':>8}" + "".join(f"{m:>11}" for m in MODES))
    print("-" * (8 + 11 * len(MODES)))
    best = (None, None, -1)
    for win in windows:
        row = ""
        for m in MODES:
            v = itr_bpm(results[m][win], n_classes, win + args.overhead)
            row += f"{v:10.1f} "
            if v > best[2]:
                best = (m, win, v)
        print(f"{win:7.1f}s" + row)

    print("\nBest configuration: %s at a %.1fs window (%.1f bits/min)"
          % (best[0], best[1], best[2]))
    if best[0] == "cca":
        print("  Calibration did not beat the training-free decoder here.")
        print("  Usually means too few trials or poor electrode contact -- more")
        print("  blocks would be the first thing to try.")
    else:
        print("  Run the BCI with:")
        print("    python ssvep_bci.py --port COM11 --model %s --mode %s --window %.1f"
              % (args.calib, best[0], best[1]))
        if best[0] == "trca":
            print("  NOTE: 'trca' is phase-dependent and ssvep_bci.py free-runs its")
            print("  flicker, so online it falls back to trca_cca. The gap between")
            print("  those two columns is what phase-locking the stimulus would win.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
