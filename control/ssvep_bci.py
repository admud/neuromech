"""Online SSVEP BCI test GUI for the 8-channel OpenBCI Cyton.

Four flickering targets drive a cursor, decoded live with filter-bank CCA.
This is the online counterpart to eeg-expy's offline visual_ssvep experiment:
no training data is needed, since CCA correlates the EEG against synthetic
sinusoid templates at each known target frequency.

    # real headset
    python ssvep_bci.py --port COM11

    # no hardware -- brainflow's synthetic board, for checking the GUI
    python ssvep_bci.py --device synthetic

    # tune
    python ssvep_bci.py --port COM11 --freqs 11,14,17,20 --window 2.0

Keys:  ESC quit   |   SPACE recentre cursor   |   D toggle debug readout
"""
import argparse
import sys
import threading
import time

import numpy as np
from scipy.signal import butter, filtfilt

from eegnb.devices.eeg import EEG
from eegnb.devices.utils import EEG_CHANNELS, EEG_INDICES

# Targets are laid out up / down / left / right.
DIRECTIONS = ["up", "down", "left", "right"]
OFFSETS = {"up": (0, 1), "down": (0, -1), "left": (-1, 0), "right": (1, 0)}

# Channels used for decoding. Missing ones are skipped.
PREFERRED_CHANNELS = ["O1", "O2", "P7", "P8"]

# Filter-bank sub-bands (Hz). Summing CCA across sub-bands that isolate
# successive harmonics beats plain CCA substantially (Chen et al. 2015).
FB_BANDS = [(6, 50), (14, 50), (22, 50)]


def fb_weights(n):
    """Sub-band weighting a*n^-b + c from the FBCCA paper."""
    return np.array([(i + 1) ** -1.25 + 0.25 for i in range(n)])


def cca_max_corr(X, Y):
    """Largest canonical correlation between the column spaces of X and Y.

    QR + SVD rather than sklearn's iterative CCA: same answer, but fast
    enough to keep up with a 0.25 s decode interval.
    """
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


def harmonic_clashes(freqs, n_harmonics=3):
    """Pairs of targets sharing a harmonic, which CCA cannot tell apart.

    e.g. 8 and 12 Hz collide at 24 Hz (8's 3rd, 12's 2nd), which measurably
    costs accuracy at low SNR.
    """
    seen, clashes = {}, []
    for f in freqs:
        for h in range(1, n_harmonics + 1):
            key = round(h * f, 3)
            if key in seen and seen[key] != f:
                clashes.append((seen[key], f, key))
            seen[key] = f
    return clashes


def reference_bank(freqs, n_samples, fs, n_harmonics=3):
    """Sin/cos reference matrices, one per target frequency."""
    t = np.arange(n_samples) / fs
    refs = []
    for f in freqs:
        cols = []
        for h in range(1, n_harmonics + 1):
            if h * f >= fs / 2:  # past Nyquist, contributes nothing
                continue
            cols.append(np.sin(2 * np.pi * h * f * t))
            cols.append(np.cos(2 * np.pi * h * f * t))
        refs.append(np.column_stack(cols))
    return refs


class Decoder(threading.Thread):
    """Pulls the newest EEG window from brainflow and scores each target.

    Runs off the stimulus thread so classification never delays a frame flip;
    a late flip corrupts the flicker that everything else depends on.
    """

    def __init__(self, board, fs, ch_rows, freqs, window_sec, margin, interval=0.25,
                 model=None, mode="cca"):
        super().__init__(daemon=True)
        self.model = model
        self.mode = mode
        self.board = board
        self.fs = int(fs)
        self.ch_rows = ch_rows
        self.freqs = freqs
        self.n_samples = int(window_sec * fs)
        self.margin = margin
        self.interval = interval
        self.refs = reference_bank(freqs, self.n_samples, self.fs)
        self.weights = fb_weights(len(FB_BANDS))
        self.filters = [butter(4, [lo, hi], btype="band", fs=self.fs, output="ba")
                        for lo, hi in FB_BANDS]

        self._lock = threading.Lock()
        self._scores = np.zeros(len(freqs))
        self._winner = None
        self._decode_ms = 0.0
        self._running = True

    @property
    def state(self):
        with self._lock:
            return self._scores.copy(), self._winner, self._decode_ms

    def stop(self):
        self._running = False

    def run(self):
        while self._running:
            t0 = time.time()
            try:
                self._step(t0)
            except Exception as exc:  # keep the GUI alive on a transient read error
                print("[decoder] %s: %s" % (type(exc).__name__, exc), file=sys.stderr)
            time.sleep(max(0.0, self.interval - (time.time() - t0)))

    def _step(self, t0):
        data = self.board.get_current_board_data(self.n_samples)
        if data.shape[1] < self.n_samples:
            return  # buffer still filling

        eeg = data[self.ch_rows, :].T.astype(np.float64)  # (samples, channels)

        if self.model is not None:
            # trained path: model wants (channels, samples)
            scores = self.model.score(eeg.T, mode=self.mode)
        else:
            scores = np.zeros(len(self.freqs))
            for (b, a), w in zip(self.filters, self.weights):
                filt = filtfilt(b, a, eeg, axis=0)
                for i, ref in enumerate(self.refs):
                    scores[i] += w * cca_max_corr(filt, ref) ** 2

        order = np.argsort(scores)[::-1]
        gap = scores[order[0]] - scores[order[1]]
        winner = int(order[0]) if gap >= self.margin else None

        with self._lock:
            self._scores = scores
            self._winner = winner
            self._decode_ms = (time.time() - t0) * 1000.0


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--device", default="cyton", help="eegnb device name, or 'synthetic'")
    p.add_argument("--port", default="COM11", help="serial port for the Cyton dongle")
    p.add_argument("--freqs", default="11,14,17,20",
                   help="four target frequencies in Hz: up,down,left,right. "
                        "Keep them clear of your alpha peak (~10 Hz) and free of "
                        "shared harmonics; spacing beyond ~2 Hz buys nothing and "
                        "pushes the top target into weaker response territory.")
    p.add_argument("--window", type=float, default=3.0,
                   help="decoding window in seconds (longer = more accurate, slower)")
    p.add_argument("--margin", type=float, default=0.06,
                   help="score gap the winner must beat the runner-up by")
    p.add_argument("--speed", type=float, default=0.35,
                   help="cursor speed in screen-heights per second")
    p.add_argument("--model", default=None,
                   help="calibration .npz from ssvep_calibrate.py; enables the "
                        "trained decoder")
    p.add_argument("--mode", default="trca_cca", choices=["cca", "trca_cca", "trca"],
                   help="scorer to use with --model (ignored without one)")
    p.add_argument("--windowed", action="store_true")
    args = p.parse_args()

    freqs = [float(x) for x in args.freqs.split(",")]
    if len(freqs) != 4:
        p.error("--freqs needs exactly four comma-separated values")

    # ---- EEG -------------------------------------------------------------
    print("Connecting to %s ..." % args.device)
    if args.device == "synthetic":
        eeg = EEG(device="synthetic")
    else:
        eeg = EEG(device=args.device, serial_port=args.port)

    names = EEG_CHANNELS[args.device]
    rows = EEG_INDICES[args.device]
    picks = [(n, r) for n, r in zip(names, rows) if n in PREFERRED_CHANNELS]
    if not picks:  # e.g. synthetic board's generic names: just take four
        picks = list(zip(names, rows))[:4]
    ch_names = [n for n, _ in picks]
    ch_rows = [r for _, r in picks]
    print("  decoding from: %s  @ %s Hz" % (", ".join(ch_names), eeg.sfreq))

    eeg.board.start_stream()
    print("  stream started, letting it settle ...")
    time.sleep(4)

    # ---- stimulus --------------------------------------------------------
    from psychopy import visual, event, core

    win = visual.Window(fullscr=not args.windowed, units="height",
                        color=[-0.85, -0.85, -0.85], allowGUI=False)
    refresh = win.getActualFrameRate(nIdentical=20, nMaxFrames=240,
                                     nWarmUpFrames=20, threshold=1)
    if refresh is None:
        refresh = 60.0
        print("  ! could not measure refresh rate, assuming 60 Hz")
    print("  refresh: %.2f Hz" % refresh)

    too_fast = [f for f in freqs if f >= refresh / 2]
    if too_fast:
        print("  ! %s Hz exceed half the refresh rate (%.1f Hz) and cannot be "
              "rendered" % (too_fast, refresh / 2))
    for a, b, h in harmonic_clashes(freqs):
        print("  ! %g and %g Hz share a harmonic at %g Hz -- CCA will confuse "
              "them at low SNR" % (a, b, h))

    targets, captions = [], []
    for direction, f in zip(DIRECTIONS, freqs):
        dx, dy = OFFSETS[direction]
        pos = (dx * 0.42, dy * 0.32)
        targets.append(visual.Rect(win, width=0.20, height=0.20, pos=pos,
                                   fillColor=[0, 0, 0], lineColor=[0.2, 0.2, 0.2],
                                   lineWidth=2, units="height"))
        captions.append(visual.TextStim(win, text="%s\n%.1f Hz" % (direction, f),
                                        pos=pos, color=[0.1, 0.1, 0.9], height=0.035,
                                        units="height", alignText="center"))

    cursor = visual.Circle(win, radius=0.022, fillColor=[0.9, 0.4, -0.5],
                           lineColor=[1, 1, 1], units="height")
    status = visual.TextStim(win, text="", pos=(0, 0.46), color=[0.4, 0.4, 0.4],
                             height=0.026, units="height")
    bars, bar_labels = [], []
    for i in range(4):
        x = -0.30 + i * 0.20
        bars.append(visual.Rect(win, width=0.05, height=0.001, pos=(x, -0.455),
                                fillColor=[-0.2, 0.6, 0.3], lineColor=None,
                                anchor="bottom", units="height"))
        bar_labels.append(visual.TextStim(win, text="", pos=(x, -0.485),
                                          color=[0.35, 0.35, 0.35], height=0.020,
                                          units="height"))

    model = None
    mode = "cca"
    if args.model:
        from ssvep_trca import FilterBankTRCA, load_calibration
        cal = load_calibration(args.model)
        n = int(args.window * cal["fs"])
        if n > cal["epochs"].shape[2]:
            print("  ! --window %.1fs exceeds the %.1fs calibration trials; "
                  "clamping" % (args.window, cal["trial_len"]))
            n = cal["epochs"].shape[2]
        if cal["ch_names"] != ch_names:
            print("  ! calibration channels %s != live channels %s"
                  % (cal["ch_names"], ch_names))
        mode = args.mode
        if mode == "trca":
            # Templates are phase-locked to trial onset; this loop free-runs its
            # flicker, so a sliding window sits at an arbitrary phase.
            print("  ! 'trca' needs phase-locked windows, which this loop does "
                  "not provide -- using trca_cca instead")
            mode = "trca_cca"
        model = FilterBankTRCA(cal["freqs"], cal["fs"]).fit(
            cal["epochs"][:, :, :n], cal["labels"])
        print("  trained decoder: %s, %d calibration trials"
              % (mode, len(cal["labels"])))

    decoder = Decoder(eeg.board, eeg.sfreq, ch_rows, freqs, args.window, args.margin,
                      model=model, mode=mode)
    decoder.start()

    pos = np.array([0.0, 0.0])
    frame = 0
    show_debug = True
    clock = core.Clock()
    last_t = clock.getTime()

    print("\nLook at a target to move the cursor.  ESC quit, SPACE recentre, D debug.\n")
    try:
        while True:
            keys = event.getKeys()
            if "escape" in keys:
                break
            if "space" in keys:
                pos[:] = 0.0
            if "d" in keys:
                show_debug = not show_debug

            scores, winner, decode_ms = decoder.state

            # Sinusoidal luminance from the frame counter, so flicker stays
            # locked to the display rather than to wall clock.
            for i, (rect, f) in enumerate(zip(targets, freqs)):
                lum = 0.5 * (1 + np.sin(2 * np.pi * f * frame / refresh))
                v = 2 * lum - 1  # psychopy rgb range is -1..1
                rect.fillColor = [v, v, v]
                if winner == i:
                    rect.lineColor = [-0.2, 1, 0.2]
                    rect.lineWidth = 6
                else:
                    rect.lineColor = [0.2, 0.2, 0.2]
                    rect.lineWidth = 2

            now = clock.getTime()
            dt = now - last_t
            last_t = now
            if winner is not None:
                dx, dy = OFFSETS[DIRECTIONS[winner]]
                pos += np.array([dx, dy], dtype=float) * args.speed * dt
                pos[0] = float(np.clip(pos[0], -0.75, 0.75))
                pos[1] = float(np.clip(pos[1], -0.40, 0.40))
            cursor.pos = pos

            for rect in targets:
                rect.draw()
            for cap in captions:
                cap.draw()
            cursor.draw()

            if show_debug:
                total = scores.sum() or 1.0
                for i, bar in enumerate(bars):
                    bar.height = max(0.001, float(scores[i] / total) * 0.16)
                    bar.fillColor = [-0.2, 1, 0.2] if winner == i else [-0.2, 0.6, 0.3]
                    bar.draw()
                    bar_labels[i].text = "%.0fHz\n%.3f" % (freqs[i], scores[i])
                    bar_labels[i].draw()
                sel = DIRECTIONS[winner] if winner is not None else "--"
                status.text = ("%s  |  %s  |  window %.1fs  |  decode %.0f ms  "
                               "|  selected: %s"
                               % (", ".join(ch_names), mode, args.window,
                                  decode_ms, sel))
                status.draw()

            win.flip()
            frame += 1
    except KeyboardInterrupt:
        pass
    finally:
        decoder.stop()
        win.close()
        try:
            eeg.board.stop_stream()
            eeg.board.release_session()
        except Exception:
            pass
        print("Closed.")


if __name__ == "__main__":
    main()
