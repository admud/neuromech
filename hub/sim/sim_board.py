"""Fake Cyton that produces SSVEPs for whatever target the "user" is looking at.

Stands in for a brainflow BoardShim as far as ssvep_bci.Decoder cares, so the
whole hub loop runs without a headset. Samples are generated lazily from the
monotonic clock at `fs`, indexed by absolute sample number so every component
stays phase-continuous across reads.

Signal per channel (µV):
  - background: 1/f-ish noise, partly shared across channels, ~10 µV rms
  - 10 Hz alpha, strongest occipitally, slowly amplitude-modulated
  - a little 50 Hz mains
  - while gazing at target i: freqs[i] plus 2nd and 3rd harmonics, strongest
    on O1/O2, weaker on P7/P8, faint elsewhere, scaled by `snr`
"""
import threading
import time

import numpy as np
from scipy.signal import lfilter

EEG_NAMES = ["Fp1", "Fp2", "C3", "C4", "P7", "P8", "O1", "O2"]
# How strongly each channel picks up the visual cortex response.
SSVEP_GAIN = np.array([0.05, 0.05, 0.15, 0.15, 0.55, 0.55, 1.0, 1.0])
ALPHA_GAIN = np.array([0.2, 0.2, 0.4, 0.4, 0.7, 0.7, 1.0, 1.0])
HARMONICS = [(1, 1.0), (2, 0.5), (3, 0.25)]   # (multiple, relative amplitude)

NOISE_UV = 10.0    # background rms
ALPHA_UV = 4.0
LINE_UV = 1.5
# Fundamental amplitude on O1/O2 is snr * SSVEP_UV. Real SSVEPs are a few µV
# against ~10-20 µV of background, i.e. snr around 0.3-0.5.
SSVEP_UV = 10.0

HISTORY_S = 10.0


class SimSSVEPBoard:
    def __init__(self, freqs, fs=250, snr=0.5, seed=None, clock=None):
        # `clock` (optional, default time.monotonic) lets tests run faster
        # than real time with a fake clock.
        self._clock = clock or time.monotonic
        self.sfreq = int(fs)
        self.eeg_rows = list(range(1, 9))
        self.eeg_names = list(EEG_NAMES)
        self.counter_row = 0
        self.timestamp_row = 9
        self.n_rows = 10
        self.snr = float(snr)

        self._lock = threading.Lock()
        self._rng = np.random.default_rng(seed)
        self._freqs = [float(f) for f in freqs]
        self._gaze = None
        # Each target gets a fixed, arbitrary response phase: the
        # phone's flicker is not phase-locked to anything the decoder knows.
        self._phase = self._rng.uniform(0, 2 * np.pi, size=len(self._freqs))
        # Small per-channel lags: nearby electrodes see roughly the same wave.
        self._ch_lag = self._rng.uniform(-0.3, 0.3, size=8)

        # 1/f-ish noise: white noise through a leaky integrator, plus white.
        self._pink_b, self._pink_a = [1.0], [1.0, -0.97]
        self._pink_zi = np.zeros((9, 1))  # 8 channels + 1 shared

        self._cap = int(HISTORY_S * self.sfreq)
        self._buf = np.zeros((self.n_rows, self._cap))
        self._count = 0          # samples written since start_stream
        self._next_index = 0     # absolute sample index of the next sample
        self._t0 = None          # monotonic time of sample 0
        self._streaming = False
        self._prepared = False

    # ---- BoardShim-ish lifecycle ----------------------------------------
    def prepare_session(self):
        self._prepared = True

    def start_stream(self, *args, **kwargs):
        with self._lock:
            self._t0 = self._clock()
            self._next_index = 0
            self._count = 0
            self._streaming = True

    def stop_stream(self):
        with self._lock:
            self._catch_up()
            self._streaming = False   # buffer freezes, like brainflow's

    def release_session(self):
        with self._lock:
            self._streaming = False
            self._prepared = False

    # ---- data ------------------------------------------------------------
    def get_current_board_data(self, n):
        with self._lock:
            self._catch_up()
            n = int(min(n, self._count, self._cap))
            if n <= 0:
                return np.zeros((self.n_rows, 0))
            end = self._count % self._cap
            idx = (np.arange(end - n, end)) % self._cap
            return self._buf[:, idx].copy()

    # ---- the simulated user ---------------------------------------------
    def set_gaze(self, index):
        if index is not None and not 0 <= index < len(self._freqs):
            raise ValueError("gaze index %r out of range" % index)
        with self._lock:
            self._catch_up()   # samples up to now keep the old gaze
            self._gaze = index

    def set_freqs(self, freqs):
        freqs = [float(f) for f in freqs]
        with self._lock:
            self._catch_up()
            if len(freqs) != len(self._freqs):
                self._phase = self._rng.uniform(0, 2 * np.pi, size=len(freqs))
                if self._gaze is not None and self._gaze >= len(freqs):
                    self._gaze = None
            self._freqs = freqs

    @property
    def gaze(self):
        return self._gaze

    # ---- generation (caller holds the lock) -----------------------------
    def _catch_up(self):
        if not self._streaming:
            return
        due = int((self._clock() - self._t0) * self.sfreq) + 1
        n_new = due - self._next_index
        if n_new <= 0:
            return
        if n_new > self._cap:   # long gap (e.g. debugger): skip to the recent past
            self._next_index = due - self._cap
            self._count += n_new - self._cap
            n_new = self._cap
        chunk = self._generate(self._next_index, n_new)
        pos = (self._count + np.arange(n_new)) % self._cap
        self._buf[:, pos] = chunk
        self._count += n_new
        self._next_index += n_new

    def _generate(self, start, n):
        fs = self.sfreq
        idx = np.arange(start, start + n)
        t = idx / fs

        white = self._rng.standard_normal((9, n))
        pink, self._pink_zi = lfilter(self._pink_b, self._pink_a, white, axis=1, zi=self._pink_zi)
        pink *= np.sqrt(1 - 0.97 ** 2)   # unit variance
        # Scaled so the total is ~NOISE_UV rms: shared + own pink + white.
        eeg = NOISE_UV * (0.5 * pink[8] + 0.6 * pink[:8]
                          + 0.6 * self._rng.standard_normal((8, n)))

        alpha_env = 1.0 + 0.5 * np.sin(2 * np.pi * 0.1 * t)
        alpha = ALPHA_UV * alpha_env * np.sin(2 * np.pi * 10.0 * t)
        eeg += ALPHA_GAIN[:, None] * alpha[None, :]
        eeg += LINE_UV * np.sin(2 * np.pi * 50.0 * t)[None, :]

        if self._gaze is not None:
            f = self._freqs[self._gaze]
            amp = self.snr * SSVEP_UV
            ph = self._phase[self._gaze]
            for h, rel in HARMONICS:
                if h * f >= fs / 2:
                    continue
                arg = 2 * np.pi * h * f * t[None, :] + h * (ph + self._ch_lag[:, None])
                eeg += (amp * rel) * SSVEP_GAIN[:, None] * np.sin(arg)

        out = np.zeros((self.n_rows, n))
        out[self.counter_row] = idx
        out[1:9] = eeg
        out[self.timestamp_row] = (self._t0 or 0.0) + t
        return out
