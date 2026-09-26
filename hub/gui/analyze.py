"""python -m hub.gui.analyze FRAMES.csv: check a --log-frames recording.

Reports the flip timing (fps, p95, late frames) and, for every stretch with
constant frequencies, the frequency each target actually flickered at,
estimated from the levels against the *measured* flip times (a DFT peak
search), so a wrong or frame-counter-based flicker would show up.
"""
import argparse
import sys

import numpy as np

from .logic import TARGETS


def load(path):
    d = np.genfromtxt(path, delimiter=",", names=True)
    return {k: np.atleast_1d(d[k]) for k in d.dtype.names}


def timing(d):
    t = d["t_flip"]
    dt = np.diff(t) * 1000
    med = float(np.median(dt))
    late = int(np.sum(dt > 1.5 * med))
    return {"frames": len(t), "seconds": float(t[-1] - t[0]),
            "fps": (len(t) - 1) / float(t[-1] - t[0]),
            "median_ms": med, "p95_ms": float(np.percentile(dt, 95)),
            "max_ms": float(dt.max()), "late": late, "late_pct": 100.0 * late / len(dt),
            # how far the prediction used for the levels was from the real flip
            "pred_err_ms_p95": float(np.percentile(np.abs(d["t_flip"] - d["t_pred"]) * 1000, 95))}


def peak_freq(t, x, lo=1.0, hi=60.0, step=0.01):
    """Frequency of the strongest sinusoid in x(t), t irregular (seconds)."""
    x = x - x.mean()
    fs = np.arange(lo, hi, step)
    best, best_f = -1.0, None
    for chunk in np.array_split(fs, max(1, len(fs) // 500)):
        ph = np.exp(-2j * np.pi * np.outer(chunk, t))
        p = np.abs(ph @ x) ** 2
        i = int(np.argmax(p))
        if p[i] > best:
            best, best_f = float(p[i]), float(chunk[i])
    return best_f


def segments(d):
    """(start, end) index ranges with constant frequencies."""
    f = np.stack([d["f_" + k] for k in TARGETS], axis=1)
    change = np.flatnonzero(np.any(np.diff(f, axis=0) != 0, axis=1)) + 1
    edges = [0, *change.tolist(), len(f)]
    return [(a, b) for a, b in zip(edges[:-1], edges[1:]) if b - a > 1]


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m hub.gui.analyze", description=__doc__)
    p.add_argument("csv")
    a = p.parse_args(argv)
    d = load(a.csv)
    tm = timing(d)
    print("%(frames)d frames over %(seconds).1f s: %(fps).2f fps, median %(median_ms).2f ms, "
          "p95 %(p95_ms).2f ms, max %(max_ms).1f ms, late %(late)d (%(late_pct).2f%%), "
          "prediction error p95 %(pred_err_ms_p95).2f ms" % tm)
    ok = True
    for s, e in segments(d):
        t = d["t_flip"][s:e]
        if t[-1] - t[0] < 1.0:
            continue
        cfg = [float(d["f_" + k][s]) for k in TARGETS]
        est = [peak_freq(t, d["L_" + k][s:e]) for k in TARGETS]
        good = all(abs(x - c) <= 0.05 for x, c in zip(est, cfg))
        ok &= good
        print("  %.1f s from t=%.1f: configured %s -> measured %s %s"
              % (t[-1] - t[0], t[0] - d["t_flip"][0], "/".join("%g" % c for c in cfg),
                 "/".join("%.2f" % x for x in est), "OK" if good else "MISMATCH"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
