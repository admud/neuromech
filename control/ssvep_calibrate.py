"""Collect cued SSVEP calibration data for training a TRCA decoder.

Runs blocks of cued trials: an arrow tells you which target to look at, the
targets flicker for a few seconds, the epoch is recorded with its label.

    python ssvep_calibrate.py --port COM11 --blocks 6 --out calib_s1.npz

Six blocks x 4 targets x 4 s is about 4 minutes of flicker plus rests -- close
to the "five minutes to calibrate" figure real SSVEP BCIs quote. Feed the
result to ssvep_eval.py to see what it buys you, then to ssvep_bci.py --model.

Two details that matter for the data being usable:

  * Flicker phase is reset at the start of every trial, so all epochs of a
    given target are phase-aligned. Template-based decoders (full TRCA) are
    meaningless without this.
  * Epochs are cut using brainflow's own sample timestamps rather than by
    counting samples after the fact, so buffering lag does not smear the
    trial boundaries.

Keys:  ESC abort (data collected so far is still saved)
"""
import argparse
import sys
import time

import numpy as np

from eegnb.devices.eeg import EEG
from eegnb.devices.utils import EEG_CHANNELS, EEG_INDICES

DIRECTIONS = ["up", "down", "left", "right"]
OFFSETS = {"up": (0, 1), "down": (0, -1), "left": (-1, 0), "right": (1, 0)}
PREFERRED_CHANNELS = ["O1", "O2", "P7", "P8"]


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--device", default="cyton")
    p.add_argument("--port", default="COM11")
    p.add_argument("--freqs", default="11,14,17,20")
    p.add_argument("--blocks", type=int, default=6,
                   help="repetitions of each target (6 x 4 targets = 24 trials)")
    p.add_argument("--trial-len", type=float, default=4.0, help="flicker seconds per trial")
    p.add_argument("--cue-len", type=float, default=1.0)
    p.add_argument("--rest-len", type=float, default=1.0)
    p.add_argument("--out", default="calib.npz")
    p.add_argument("--windowed", action="store_true")
    args = p.parse_args()

    freqs = [float(x) for x in args.freqs.split(",")]
    if len(freqs) != 4:
        p.error("--freqs needs exactly four comma-separated values")

    print("Connecting to %s ..." % args.device)
    eeg = (EEG(device="synthetic") if args.device == "synthetic"
           else EEG(device=args.device, serial_port=args.port))

    names = EEG_CHANNELS[args.device]
    rows = EEG_INDICES[args.device]
    picks = [(n, r) for n, r in zip(names, rows) if n in PREFERRED_CHANNELS]
    if not picks:
        picks = list(zip(names, rows))[:4]
    ch_names = [n for n, _ in picks]
    ch_rows = [r for _, r in picks]
    ts_row = eeg.timestamp_channel
    fs = int(eeg.sfreq)
    print("  recording from: %s  @ %d Hz" % (", ".join(ch_names), fs))

    eeg.board.start_stream()
    print("  stream started, settling ...")
    time.sleep(4)

    from psychopy import visual, event, core

    win = visual.Window(fullscr=not args.windowed, units="height",
                        color=[-0.85, -0.85, -0.85], allowGUI=False)
    refresh = win.getActualFrameRate(nIdentical=20, nMaxFrames=240,
                                     nWarmUpFrames=20, threshold=1) or 60.0
    print("  refresh: %.2f Hz" % refresh)

    targets, captions = [], []
    for direction, f in zip(DIRECTIONS, freqs):
        dx, dy = OFFSETS[direction]
        pos = (dx * 0.42, dy * 0.32)
        targets.append(visual.Rect(win, width=0.20, height=0.20, pos=pos,
                                   fillColor=[0, 0, 0], lineColor=[0.2, 0.2, 0.2],
                                   lineWidth=2, units="height"))
        captions.append(visual.TextStim(win, text="%s\n%.0f Hz" % (direction, f),
                                        pos=pos, color=[0.1, 0.1, 0.9], height=0.035,
                                        units="height", alignText="center"))
    cue = visual.TextStim(win, text="", pos=(0, 0), color=[1, 0.5, -0.5],
                          height=0.09, units="height")
    banner = visual.TextStim(win, text="", pos=(0, 0.45), color=[0.45, 0.45, 0.45],
                             height=0.030, units="height")

    # trial order: each block is one shuffled pass over all four targets
    rng = np.random.default_rng()
    order = []
    for _ in range(args.blocks):
        idx = np.arange(4)
        rng.shuffle(idx)
        order.extend(int(i) for i in idx)

    n_expect = int(args.trial_len * fs)
    epochs, labels = [], []

    def draw_targets(frame, highlight=None, flicker=True):
        for i, (rect, f) in enumerate(zip(targets, freqs)):
            if flicker:
                lum = 0.5 * (1 + np.sin(2 * np.pi * f * frame / refresh))
                v = 2 * lum - 1
            else:
                v = -0.4
            rect.fillColor = [v, v, v]
            if highlight == i:
                rect.lineColor = [1, 0.5, -0.5]
                rect.lineWidth = 7
            else:
                rect.lineColor = [0.2, 0.2, 0.2]
                rect.lineWidth = 2
            rect.draw()
        for cap in captions:
            cap.draw()

    aborted = False
    print("\nLook at whichever target the arrow points to. ESC aborts.\n")
    try:
        # brief lead-in so the participant is settled before the first cue
        t0 = time.time()
        while time.time() - t0 < 2.0:
            draw_targets(0, flicker=False)
            banner.text = "get ready ..."
            banner.draw()
            win.flip()
            if "escape" in event.getKeys():
                raise KeyboardInterrupt

        for trial_i, k in enumerate(order):
            banner.text = "trial %d / %d" % (trial_i + 1, len(order))

            # --- cue: static targets, arrow marks the one to look at --------
            cue.text = {"up": "^", "down": "v", "left": "<", "right": ">"}[DIRECTIONS[k]]
            t0 = time.time()
            while time.time() - t0 < args.cue_len:
                draw_targets(0, highlight=k, flicker=False)
                cue.draw()
                banner.draw()
                win.flip()
                if "escape" in event.getKeys():
                    raise KeyboardInterrupt

            # --- flicker: phase reset at frame 0, this is the recorded epoch -
            event.clearEvents()
            frame = 0
            t_start = time.time()
            while (time.time() - t_start) < args.trial_len:
                draw_targets(frame, highlight=k, flicker=True)
                banner.draw()
                win.flip()
                frame += 1
                if "escape" in event.getKeys():
                    raise KeyboardInterrupt
            t_end = time.time()

            # --- rest, and pull the epoch out by timestamp ------------------
            t0 = time.time()
            while time.time() - t0 < args.rest_len:
                draw_targets(0, flicker=False)
                banner.draw()
                win.flip()

            grab = int((args.trial_len + args.rest_len + 2.0) * fs)
            data = eeg.board.get_current_board_data(grab)
            ts = data[ts_row, :]
            sel = (ts >= t_start) & (ts <= t_end)
            n_sel = int(sel.sum())
            if n_sel < int(0.9 * n_expect):
                print("  trial %d (%s): only %d/%d samples, dropped"
                      % (trial_i + 1, DIRECTIONS[k], n_sel, n_expect))
                continue
            ep = data[ch_rows, :][:, sel][:, :n_expect]
            if ep.shape[1] < n_expect:  # pad the odd short trial by edge-repeat
                pad = n_expect - ep.shape[1]
                ep = np.pad(ep, ((0, 0), (0, pad)), mode="edge")
            epochs.append(ep)
            labels.append(k)
            print("  trial %d/%d  %-5s %4.0f Hz   %d samples"
                  % (trial_i + 1, len(order), DIRECTIONS[k], freqs[k], n_sel))

    except KeyboardInterrupt:
        aborted = True
        print("\nAborted -- saving what was collected.")
    finally:
        win.close()
        try:
            eeg.board.stop_stream()
            eeg.board.release_session()
        except Exception:
            pass

    if not epochs:
        print("No usable trials recorded; nothing saved.")
        return 1

    epochs = np.stack(epochs)
    labels = np.asarray(labels, dtype=int)
    np.savez_compressed(args.out, epochs=epochs, labels=labels, freqs=np.array(freqs),
                        fs=fs, ch_names=np.array(ch_names), trial_len=args.trial_len)
    counts = {DIRECTIONS[i]: int((labels == i).sum()) for i in range(4)}
    print("\nSaved %s" % args.out)
    print("  %d trials  %s" % (len(labels), counts))
    print("  epochs shape %s  (trials, channels, samples)" % (epochs.shape,))
    if aborted:
        print("  NOTE: run was aborted, classes may be unbalanced")
    print("\nNext:  python ssvep_eval.py %s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
