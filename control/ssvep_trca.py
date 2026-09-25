"""Calibrated SSVEP decoders: TRCA and friends.

Three scorers, in increasing order of what they demand from calibration data:

  cca       No training at all. Canonical correlation against generic sin/cos
            templates. Phase-invariant, so it works on a freely-sliding window.

  trca_cca  TRCA learns a spatial filter from your calibration data, but
            frequency matching still goes through the phase-invariant sin/cos
            basis. Usable online exactly like plain CCA.

  trca      Full ensemble TRCA: spatial filter *and* an averaged individual
            template per target. Strongest in the literature, but correlating
            against a template is phase-dependent, so the test window must sit
            at the same stimulus phase the calibration trials did.

That last constraint is the reason ssvep_calibrate.py resets flicker phase at
the start of every trial: it keeps the epochs phase-aligned so `trca` is
measurable offline. Whether it beats `trca_cca` by enough to justify
phase-locking the online loop is an empirical question -- ssvep_eval.py
answers it on your own data rather than on a claim from a paper.

References:
  Nakanishi et al. 2018, "Enhancing detection of SSVEPs for a high-speed BCI"
  Chen et al. 2015, "Filter bank canonical correlation analysis"
"""
import numpy as np
from scipy.linalg import eigh
from scipy.signal import butter, filtfilt

FB_BANDS = [(6, 50), (14, 50), (22, 50)]


def fb_weights(n):
    return np.array([(i + 1) ** -1.25 + 0.25 for i in range(n)])


def make_filters(fs, bands=FB_BANDS):
    return [butter(4, [lo, hi], btype="band", fs=fs, output="ba") for lo, hi in bands]


def corr2(a, b):
    """Pearson correlation between two flattened arrays."""
    a = np.asarray(a).ravel()
    b = np.asarray(b).ravel()
    a = a - a.mean()
    b = b - b.mean()
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0
    return float(np.clip(a @ b / denom, -1.0, 1.0))


def cca_max_corr(X, Y):
    """Largest canonical correlation. X, Y are (n_samples, n_features)."""
    X = X - X.mean(axis=0)
    Y = Y - Y.mean(axis=0)
    if not np.all(np.isfinite(X)) or not np.all(np.isfinite(Y)):
        return 0.0
    try:
        Qx, _ = np.linalg.qr(X)
        Qy, _ = np.linalg.qr(Y)
        s = np.linalg.svd(Qx.T @ Qy, compute_uv=False)
    except np.linalg.LinAlgError:
        return 0.0
    return float(np.clip(s[0], 0.0, 1.0))


def reference_bank(freqs, n_samples, fs, n_harmonics=3):
    """Sin/cos reference matrices, one per target frequency."""
    t = np.arange(n_samples) / fs
    refs = []
    for f in freqs:
        cols = []
        for h in range(1, n_harmonics + 1):
            if h * f >= fs / 2:
                continue
            cols.append(np.sin(2 * np.pi * h * f * t))
            cols.append(np.cos(2 * np.pi * h * f * t))
        refs.append(np.column_stack(cols))
    return refs


def trca_spatial_filter(X, reg=1e-6):
    """TRCA spatial filter for one class.

    X : (n_trials, n_channels, n_samples) -- trials of the *same* target.

    Maximises reproducibility across trials: the ratio of between-trial
    covariance (the part of the signal that repeats every time the same
    stimulus is shown) to total covariance.
    """
    n_trials, n_ch, _ = X.shape
    Xc = X - X.mean(axis=2, keepdims=True)

    # sum_h X_h X_h^T  == covariance of the trials concatenated in time
    Q = np.einsum("hct,hdt->cd", Xc, Xc)

    # sum over ordered pairs h1 != h2, via (sum_h X_h)(sum_h X_h)^T - diagonal
    U = Xc.sum(axis=0)
    S = U @ U.T - Q

    Q = Q + reg * np.trace(Q) / n_ch * np.eye(n_ch)  # keep Q invertible
    try:
        vals, vecs = eigh(S, Q)
    except np.linalg.LinAlgError:
        return np.ones(n_ch) / np.sqrt(n_ch)
    return vecs[:, -1]  # eigenvector of the largest eigenvalue


class FilterBankTRCA:
    """Filter-bank TRCA supporting all three scoring modes.

    Fit on epochs shaped (n_trials, n_channels, n_samples) with integer labels
    indexing `freqs`.
    """

    def __init__(self, freqs, fs, bands=FB_BANDS, n_harmonics=3):
        self.freqs = list(freqs)
        self.fs = int(fs)
        self.bands = bands
        self.n_harmonics = n_harmonics
        self.filters = make_filters(self.fs, bands)
        self.weights = fb_weights(len(bands))
        self.W = None          # (n_bands, n_classes, n_channels)
        self.templates = None  # (n_bands, n_classes, n_channels, n_samples)
        self.n_samples = None

    def _subband(self, X, bi):
        b, a = self.filters[bi]
        return filtfilt(b, a, X, axis=-1)

    def fit(self, epochs, labels):
        epochs = np.asarray(epochs, dtype=np.float64)
        labels = np.asarray(labels)
        n_classes = len(self.freqs)
        _, n_ch, n_samp = epochs.shape
        self.n_samples = n_samp

        W = np.zeros((len(self.bands), n_classes, n_ch))
        T = np.zeros((len(self.bands), n_classes, n_ch, n_samp))
        for bi in range(len(self.bands)):
            Xb = self._subband(epochs, bi)
            for k in range(n_classes):
                Xk = Xb[labels == k]
                if len(Xk) == 0:
                    W[bi, k] = np.ones(n_ch) / np.sqrt(n_ch)
                    continue
                W[bi, k] = trca_spatial_filter(Xk)
                T[bi, k] = Xk.mean(axis=0)
        self.W = W
        self.templates = T
        return self

    def score(self, window, mode="trca_cca"):
        """Score a single test window, shaped (n_channels, n_samples).

        Returns one score per target frequency.
        """
        window = np.asarray(window, dtype=np.float64)
        n_samp = window.shape[1]
        n_classes = len(self.freqs)
        scores = np.zeros(n_classes)

        if mode == "cca":
            refs = reference_bank(self.freqs, n_samp, self.fs, self.n_harmonics)
            for bi, w in enumerate(self.weights):
                Xb = self._subband(window, bi)
                for k in range(n_classes):
                    scores[k] += w * cca_max_corr(Xb.T, refs[k]) ** 2
            return scores

        if self.W is None:
            raise RuntimeError("model is not fitted; call fit() first")

        if mode == "trca_cca":
            refs = reference_bank(self.freqs, n_samp, self.fs, self.n_harmonics)
            for bi, w in enumerate(self.weights):
                Xb = self._subband(window, bi)
                for k in range(n_classes):
                    # project through this class's learned spatial filter, then
                    # match frequency phase-invariantly
                    proj = (self.W[bi, k] @ Xb)[:, None]
                    scores[k] += w * cca_max_corr(proj, refs[k]) ** 2
            return scores

        if mode == "trca":
            m = min(n_samp, self.n_samples)
            for bi, w in enumerate(self.weights):
                Xb = self._subband(window, bi)[:, :m]
                Wb = self.W[bi]                      # (n_classes, n_channels)
                for k in range(n_classes):
                    # ensemble: project test and template through *all* filters
                    a = Wb @ Xb
                    b = Wb @ self.templates[bi, k][:, :m]
                    r = corr2(a, b)
                    scores[k] += w * np.sign(r) * r ** 2
            return scores

        raise ValueError("unknown mode: %s" % mode)

    def predict(self, window, mode="trca_cca"):
        return int(np.argmax(self.score(window, mode=mode)))


def load_calibration(path):
    """Load an ssvep_calibrate.py .npz file."""
    d = np.load(path, allow_pickle=True)
    return {
        "epochs": d["epochs"],            # (n_trials, n_channels, n_samples)
        "labels": d["labels"],
        "freqs": [float(f) for f in d["freqs"]],
        "fs": int(d["fs"]),
        "ch_names": [str(c) for c in d["ch_names"]],
        "trial_len": float(d["trial_len"]),
    }
