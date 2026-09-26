"""Jaw-clench detector for the Cyton: a port of the Muse `blink_clench_v2.py` clench path.

A clench is a burst of broadband muscle EMG, far above 30 Hz, on every scalp
channel (most on the frontal and temporal ones). Chain, per channel:

  50 + 100 Hz notch   the Cyton carries mains, which would dominate >30 Hz.
                      Wide (Q=5, 45-55 / 90-110 Hz): a narrow notch lets a
                      changing mains amplitude leak through its sidebands,
                      and the calm baseline above 30 Hz is so quiet that the
                      leak alone crossed the threshold
  30 Hz high-pass     4th-order Butterworth, causal (streaming)
  TKEO                Teager-Kaiser energy x[n]^2 - x[n-1]x[n+1]: tracks
                      amplitude AND frequency, so EMG stands out from slow
                      artefacts (measured ~50x clench/rest on the Muse)
  envelope            50 ms moving average
  robust z            (env - median) / (1.4826 MAD) over a rolling 8 s
                      baseline that only learns while calm

Channels are combined by the 2nd-largest z: a clench shows on all of them,
while a cable bump or a single bad electrode shows on one.

The clench fires when the combined z stays above `threshold` for `min_s`
(50 ms). Unlike the Muse version it fires ONCE per burst: it re-arms only
after z has stayed below half the threshold for 100 ms, and never within
`refractory_s` (0.4 s) of the last fire. A 1 s clench whose envelope wobbles
around the threshold must not latch and then immediately unlatch.

Feed it the new samples every engine tick with `update(chunk)`.
"""
from collections import deque

import numpy as np
from scipy.signal import butter, iirnotch, sosfilt, sosfilt_zi, tf2sos

DEFAULT_CHANNELS = ["Fp1", "Fp2", "P7", "P8"]
DEFAULT_THRESHOLD = 8.0


def _design(fs, mains=50.0):
    """Notch(es) then high-pass, as one SOS cascade."""
    parts = []
    for f in (mains, 2 * mains):
        if f < fs / 2 - 1:
            b, a = iirnotch(f, Q=5.0, fs=fs)
            parts.append(tf2sos(b, a))
    parts.append(butter(4, 30.0, btype="highpass", fs=fs, output="sos"))
    return np.vstack(parts)


class ClenchDetector:
    def __init__(self, fs, n_channels, threshold=DEFAULT_THRESHOLD, min_s=0.05,
                 refractory_s=0.4, baseline_s=8.0, env_s=0.05, mains=50.0,
                 warmup_s=1.0):
        self.fs = int(fs)
        self.n = int(n_channels)
        self.threshold = float(threshold)
        self.min_n = max(1, int(round(min_s * self.fs)))
        self.refractory_n = int(round(refractory_s * self.fs))
        self.warmup_n = int(warmup_s * self.fs)
        self.rearm_n = max(1, int(round(0.1 * self.fs)))
        self._sos = _design(self.fs, mains)
        self._zi = None
        self._prev = np.zeros((self.n, 2))           # last two filtered samples, for TKEO
        self._env_n = max(1, int(round(env_s * self.fs)))
        self._tk_tail = np.zeros((self.n, self._env_n - 1))
        # Baseline: every 2nd calm envelope sample over baseline_s.
        self._base = deque(maxlen=max(10, int(baseline_s * self.fs / 2)))
        self._base_step = 0
        self._med = np.zeros(self.n)
        self._mad = np.ones(self.n)
        self._stats_ok = False

        self.t = 0                 # samples processed
        self._run = 0              # consecutive samples above threshold
        self._armed = True         # False after a fire until z has been low for rearm_n
        self._low = 0              # consecutive samples below threshold/2
        self._last_fire = -10**9
        self.z = 0.0               # latest combined z
        self.z_peak = 0.0          # max combined z in the last update() call
        self.zs = np.zeros(0)      # combined z per sample of the last update() call
        self.count = 0

    def reset(self):
        self.__init__(self.fs, self.n, self.threshold, self.min_n / self.fs,
                      self.refractory_n / self.fs, self._base.maxlen * 2 / self.fs,
                      self._env_n / self.fs, warmup_s=self.warmup_n / self.fs)

    # ---- streaming -------------------------------------------------------
    def update(self, x):
        """Process a (n_channels, n) chunk in µV. Returns, one per fire, the
        offset of the clench's START relative to this chunk's first sample
        (negative when the burst began in an earlier chunk)."""
        x = np.asarray(x, dtype=np.float64)
        if x.ndim != 2 or x.shape[0] != self.n or x.shape[1] == 0:
            self.z_peak = self.z
            self.zs = np.zeros(0)
            return []
        if self._zi is None:
            # Start the filter at the first sample's DC level: the Cyton's
            # offsets are thousands of µV and would ring for seconds otherwise.
            self._zi = sosfilt_zi(self._sos)[:, None, :] * x[None, :, :1]
        y, self._zi = sosfilt(self._sos, x, axis=1, zi=self._zi)

        ext = np.concatenate([self._prev, y], axis=1)
        tk = np.maximum(ext[:, 1:-1] ** 2 - ext[:, :-2] * ext[:, 2:], 0.0)   # one sample late
        self._prev = ext[:, -2:]

        seq = np.concatenate([self._tk_tail, tk], axis=1)
        c = np.cumsum(np.concatenate([np.zeros((self.n, 1)), seq], axis=1), axis=1)
        env = (c[:, self._env_n:] - c[:, :-self._env_n]) / self._env_n
        if self._env_n > 1:
            self._tk_tail = seq[:, -(self._env_n - 1):]

        fires = []
        zs = np.empty(env.shape[1])
        for i in range(env.shape[1]):
            e = env[:, i]
            if self._stats_ok:
                zch = (e - self._med) / self._mad
                zc = float(np.sort(zch)[-2]) if self.n >= 2 else float(zch[0])
            else:
                zc = 0.0
            zs[i] = zc
            above = zc > self.threshold
            if above:
                self._run += 1
                if (self._armed and self._run >= self.min_n
                        and self.t - self._last_fire >= self.refractory_n):
                    self._armed = False
                    self._last_fire = self.t
                    self.count += 1
                    fires.append(i - self._run + 1)
            else:
                self._run = 0
            if zc < 0.5 * self.threshold:
                self._low += 1
                if self._low >= self.rearm_n:
                    self._armed = True
            else:
                self._low = 0
            calm = zc < 0.5 * self.threshold and self.t - self._last_fire > self.refractory_n
            if calm or not self._stats_ok:
                self._base_step += 1
                if self._base_step % 2 == 0:
                    self._base.append(e.copy())
            self.t += 1
            if self.t % 16 == 0 and len(self._base) >= min(self.warmup_n // 2, self._base.maxlen):
                self._refresh_stats()
        self.zs = zs
        self.z = float(zs[-1]) if zs.size else self.z
        self.z_peak = float(zs.max()) if zs.size else self.z
        return fires

    def _refresh_stats(self):
        b = np.asarray(self._base)
        self._med = np.median(b, axis=0)
        mad = np.median(np.abs(b - self._med), axis=0) * 1.4826
        self._mad = np.maximum(mad, 1e-9 + 1e-6 * np.abs(self._med))
        self._stats_ok = True


def pick_clench_channels(names, rows, wanted=None):
    """Rows for the clench channels (default Fp1, Fp2, P7, P8), else the first four."""
    wanted = wanted or DEFAULT_CHANNELS
    picks = [(n, r) for n, r in zip(names, rows) if n in wanted]
    if len(picks) < 2:
        picks = list(zip(names, rows))[:4]
    return [n for n, _ in picks], [r for _, r in picks]


# ---- offline analysis of a record_clench recording -----------------------

def run_offline(data, fs, threshold=DEFAULT_THRESHOLD, chunk=12):
    """Stream a (channels, samples) array through the detector in engine-sized
    chunks. Returns (combined z per sample, fire onset sample indices)."""
    det = ClenchDetector(fs, data.shape[0], threshold=threshold)
    z = np.zeros(data.shape[1])
    fires = []
    for s in range(0, data.shape[1], chunk):
        part = data[:, s:s + chunk]
        f = det.update(part)
        fires += [s + k for k in f]
        z[s:s + part.shape[1]] = det.zs
    return z, fires


def analyze_recording(rec, channels=None, threshold=None):
    """Text report: clench-vs-rest z separation, a suggested threshold, and
    detections / false alarms at that threshold."""
    fs = rec["fs"]
    names, idx = pick_clench_channels(rec["ch_names"], list(range(len(rec["ch_names"]))), channels)
    data = rec["data"][idx]
    markers = rec["markers"]
    lag = int(0.8 * fs)   # people react to a beep a few hundred ms late
    cues = [(l, s, e + lag) for l, s, e in markers if l in ("clench", "look_clench")]
    # Relax gaps start right after a cue: skip the late tail of that clench.
    calm = [(l, s + (lag if l == "relax" else 0), e) for l, s, e in markers
            if l in ("rest", "relax", "blink") and e > s + (lag if l == "relax" else 0)]
    # z with detection effectively off, to see the raw distributions
    z, _ = run_offline(data, fs, threshold=1e9)
    out = ["channels: %s   fs %d Hz   %.0f s" % (", ".join(names), fs, data.shape[1] / fs)]
    peaks = [z[s:e].max() for _, s, e in cues if e <= len(z)]
    calm_z = np.concatenate([z[s:e] for _, s, e in calm if e <= len(z)] or [np.zeros(1)])
    by = {}
    for l, s, e in calm:
        by.setdefault(l, []).append(z[s:e])
    out.append("clench cues: %d   peak z: min %.1f  median %.1f  max %.1f"
               % (len(peaks), min(peaks or [0]), np.median(peaks or [0]), max(peaks or [0])))
    for l, arrs in by.items():
        a = np.concatenate(arrs)
        out.append("%-6s  z p99 %.1f  max %.1f" % (l, np.percentile(a, 99), a.max()))
    # Suggest: between the loudest calm moment and the weakest clench, geometric mean.
    calm_max = float(calm_z.max())
    weak = float(min(peaks)) if peaks else float("nan")
    if peaks and weak > calm_max:
        suggest = float(np.sqrt(max(calm_max, 1.0) * weak))
        out.append("separation: weakest clench %.1f vs loudest calm %.1f (%.1fx) -> suggest threshold %.1f"
                   % (weak, calm_max, weak / max(calm_max, 1e-9), suggest))
    else:
        suggest = float(np.percentile(peaks, 20)) if peaks else DEFAULT_THRESHOLD
        out.append("! clenches and calm overlap (weakest clench %.1f <= loudest calm %.1f); "
                   "suggest threshold %.1f and check electrode contact" % (weak, calm_max, suggest))
    for th in sorted({round(suggest, 1), DEFAULT_THRESHOLD} | ({threshold} if threshold else set())):
        _, fires = run_offline(data, fs, threshold=th)
        hit = sum(any(s <= f < e for f in fires) for _, s, e in cues)
        false = [f for f in fires if not any(s <= f < e for _, s, e in cues)]
        calm_s = sum(e - s for _, s, e in calm) / fs
        in_calm = [f for f in false if any(s <= f < e for _, s, e in calm)]
        doubles = sum(max(0, sum(s <= f < e for f in fires) - 1) for _, s, e in cues)
        out.append("threshold %5.1f: detected %d/%d cues, %d double-fires, %d false alarms "
                   "(%d in %.0f s of rest/blink = %.1f/min)"
                   % (th, hit, len(cues), doubles, len(false), len(in_calm), calm_s,
                      60 * len(in_calm) / max(calm_s, 1e-9)))
    return "\n".join(out)
