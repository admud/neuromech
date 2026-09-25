"""Live electrode-contact dashboard for the OpenBCI Cyton.

    python contact_viz.py --port COM11

Three views, updating ~10x/second while you adjust the headset:

  left    stacked time-domain traces, 1-45 Hz. Flat line = no contact;
          wandering baseline = loose electrode; sharp steps = cable movement.
  top r.  power spectrum per channel. Real EEG falls off with frequency
          (1/f) and usually shows an alpha bump near 10 Hz. A flat spectrum
          means you are looking at noise, not brain. Mains hum shows as a
          spike at 50 or 60 Hz.
  bot r.  per-channel verdict: amplitude, mains contamination, and a 1/f
          score that separates real EEG from junk.

Press A to run the alpha test: 8 s eyes open, then 8 s eyes closed. Occipital
alpha should rise sharply when your eyes shut. This is the definitive check
that O1/O2 are actually on your scalp -- a dead or floating electrode cannot
produce alpha blocking.

Keys:  A alpha test   |   R reset autoscale   |   Q quit
"""
import argparse
import sys
import time

import numpy as np
import matplotlib
# --snapshot renders offscreen; the interactive dashboard needs a real GUI backend
matplotlib.use("Agg" if "--snapshot" in sys.argv else "TkAgg")
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
from scipy.signal import butter, filtfilt, welch, detrend

from eegnb.devices.eeg import EEG
from eegnb.devices.utils import EEG_CHANNELS, EEG_INDICES

OCCIPITAL = ["O1", "O2", "P7", "P8", "Oz", "POz", "PO7", "PO8"]
GOOD_LO, GOOD_HI = 1.0, 9.0      # eegnb's OpenBCI thresholds, uV
ALPHA_BAND = (8.0, 12.0)


def bandpower(f, p, lo, hi):
    m = (f >= lo) & (f <= hi)
    if not m.any():
        return 0.0
    integrate = getattr(np, "trapezoid", np.trapz)
    return float(integrate(p[m], f[m]))


def verdict(std, mains_ratio, oneover_f):
    """Human-readable judgement for one channel."""
    if std < 0.3:
        return "NO CONTACT", "#d64545"
    if std < GOOD_LO:
        return "weak", "#d68b45"
    if std > 50:
        return "RAILING", "#d64545"
    if std > GOOD_HI:
        return "noisy", "#d68b45"
    if mains_ratio > 0.5:
        return "mains hum", "#d68b45"
    if oneover_f < 1.5:
        return "flat/no EEG", "#d68b45"
    return "good", "#3f9e5a"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--device", default="cyton")
    ap.add_argument("--port", default="COM11")
    ap.add_argument("--seconds", type=float, default=5.0, help="trace window length")
    ap.add_argument("--mains", type=float, default=None,
                    help="mains frequency; default auto-detects 50 vs 60 Hz")
    ap.add_argument("--snapshot", default=None,
                    help="render a few frames to this PNG and exit, instead of "
                         "opening the live dashboard")
    args = ap.parse_args()

    print("Connecting to %s ..." % args.device)
    eeg = (EEG(device="synthetic") if args.device == "synthetic"
           else EEG(device=args.device, serial_port=args.port))
    names = list(EEG_CHANNELS[args.device])
    rows = list(EEG_INDICES[args.device])
    fs = int(eeg.sfreq)
    n_ch = len(rows)
    n_win = int(args.seconds * fs)
    print("  %d channels @ %d Hz: %s" % (n_ch, fs, ", ".join(names)))

    eeg.board.start_stream()
    # must outlast the trace window, or the first frames have nothing to plot
    settle = max(3.0, args.seconds + 2.0)
    print("  stream started, filling a %.0fs buffer ..." % settle)
    time.sleep(settle)

    bp_b, bp_a = butter(4, [1, 45], btype="band", fs=fs, output="ba")

    # ---- figure ----------------------------------------------------------
    fig = plt.figure(figsize=(15, 8.5))
    fig.canvas.manager.set_window_title("EEG contact check")
    gs = GridSpec(2, 2, figure=fig, width_ratios=[1.25, 1], height_ratios=[1, 1],
                  hspace=0.28, wspace=0.22, left=0.07, right=0.98, top=0.90, bottom=0.08)
    ax_tr = fig.add_subplot(gs[:, 0])
    ax_ps = fig.add_subplot(gs[0, 1])
    ax_bar = fig.add_subplot(gs[1, 1])

    t = np.arange(n_win) / fs
    spacing = 60.0  # uV between stacked traces
    offsets = np.arange(n_ch)[::-1] * spacing
    trace_lines = []
    for i, nm in enumerate(names):
        hot = nm in OCCIPITAL
        ln, = ax_tr.plot(t, np.zeros(n_win) + offsets[i],
                         lw=0.9 if not hot else 1.2,
                         color="#2b6cb0" if hot else "#8a8a8a")
        trace_lines.append(ln)
    ax_tr.set_yticks(offsets)
    ax_tr.set_yticklabels(names)
    for lbl, nm in zip(ax_tr.get_yticklabels(), names):
        if nm in OCCIPITAL:
            lbl.set_color("#2b6cb0")
            lbl.set_fontweight("bold")
    ax_tr.set_ylim(-spacing, offsets[0] + spacing)
    ax_tr.set_xlim(0, args.seconds)
    ax_tr.set_xlabel("seconds")
    ax_tr.set_title("traces, 1-45 Hz  (occipital in blue)", fontsize=10)
    ax_tr.grid(alpha=0.15)

    psd_lines = []
    for i, nm in enumerate(names):
        hot = nm in OCCIPITAL
        ln, = ax_ps.plot([], [], lw=1.4 if hot else 0.8,
                         color="#2b6cb0" if hot else "#c0c0c0",
                         label=nm if hot else None, zorder=3 if hot else 1)
        psd_lines.append(ln)
    ax_ps.set_xlim(1, 70)
    ax_ps.set_yscale("log")
    ax_ps.set_xlabel("Hz")
    ax_ps.set_ylabel("power")
    ax_ps.set_title("spectrum  (want 1/f falloff + alpha bump near 10 Hz)", fontsize=10)
    ax_ps.grid(alpha=0.15, which="both")
    ax_ps.axvspan(ALPHA_BAND[0], ALPHA_BAND[1], color="#3f9e5a", alpha=0.10, zorder=0)
    if any(nm in OCCIPITAL for nm in names):
        ax_ps.legend(fontsize=8, loc="upper right", ncol=2)

    bars = ax_bar.barh(np.arange(n_ch)[::-1], np.zeros(n_ch), color="#999999", height=0.62)
    ax_bar.axvline(GOOD_LO, color="#3f9e5a", ls=":", lw=1)
    ax_bar.axvline(GOOD_HI, color="#3f9e5a", ls=":", lw=1)
    ax_bar.set_yticks(np.arange(n_ch)[::-1])
    ax_bar.set_yticklabels(names)
    ax_bar.set_xlim(0, 30)
    ax_bar.set_xlabel("amplitude, uV std (1-45 Hz)   -- green band = good")
    ax_bar.set_title("per-channel verdict", fontsize=10)
    ax_bar.grid(alpha=0.15, axis="x")
    # y in data coords, x in axes fraction: text stays pinned right as bars grow
    bar_texts = [ax_bar.text(0.985, y, "", va="center", ha="right", fontsize=8.5,
                             transform=ax_bar.get_yaxis_transform(),
                             bbox=dict(fc="white", ec="none", alpha=0.75, pad=1.2))
                 for y in np.arange(n_ch)[::-1]]

    banner = fig.text(0.5, 0.955, "", ha="center", fontsize=12, color="#333333")
    hint = fig.text(0.5, 0.925, "A = alpha test   R = rescale   Q = quit",
                    ha="center", fontsize=9, color="#888888")

    # ---- alpha test state machine ---------------------------------------
    state = {"phase": "idle", "t0": 0.0, "open": None, "closed": None, "report": ""}
    PHASE_SEC = 8.0

    def on_key(ev):
        if ev.key in ("q", "escape"):
            plt.close(fig)
        elif ev.key == "r":
            ax_bar.set_xlim(0, 30)
        elif ev.key == "a" and state["phase"] == "idle":
            state.update(phase="open", t0=time.time(), open=None, closed=None, report="")

    fig.canvas.mpl_connect("key_press_event", on_key)

    mains_hz = args.mains

    def update(_):
        nonlocal mains_hz
        data = eeg.board.get_current_board_data(n_win)
        if data.shape[1] < n_win:
            banner.set_text("buffering ...")
            return
        raw = data[rows, :].astype(np.float64)
        raw = detrend(raw, axis=1)
        filt = filtfilt(bp_b, bp_a, raw, axis=1)

        f, p = welch(raw, fs=fs, nperseg=min(n_win, fs * 2), axis=1)
        stds = filt.std(axis=1)
        alphas = np.array([bandpower(f, p[i], *ALPHA_BAND) for i in range(n_ch)])

        if mains_hz is None:  # pick whichever line is actually present
            p50 = np.mean([bandpower(f, p[i], 49, 51) for i in range(n_ch)])
            p60 = np.mean([bandpower(f, p[i], 59, 61) for i in range(n_ch)])
            mains_hz = 50.0 if p50 >= p60 else 60.0
            ax_ps.axvline(mains_hz, color="#d64545", ls=":", lw=1, zorder=2)

        # scale traces off the typical channel so normal EEG fills its lane;
        # genuinely huge channels still clip, which is itself the diagnosis
        med = float(np.median(stds))
        gain = float(np.clip((spacing * 0.35) / max(med * 2.5, 1e-6), 1e-3, 1e3))
        for i in range(n_ch):
            y = np.clip(filt[i] * gain, -spacing * 0.48, spacing * 0.48)
            trace_lines[i].set_ydata(y + offsets[i])
            psd_lines[i].set_data(f, np.maximum(p[i], 1e-12))
        ax_tr.set_title("traces, 1-45 Hz  (occipital in blue)   |   %.0f uV per lane"
                        % (spacing * 0.96 / gain), fontsize=10)

        finite = p[np.isfinite(p) & (p > 0)]
        if finite.size:
            ax_ps.set_ylim(max(finite.min() * 0.5, 1e-12), finite.max() * 2.0)

        worst = 0.0
        for i in range(n_ch):
            mains_p = bandpower(f, p[i], mains_hz - 1.5, mains_hz + 1.5)
            broad_p = bandpower(f, p[i], 2, 45) or 1e-12
            mains_ratio = mains_p / broad_p
            lo_p = bandpower(f, p[i], 2, 8) or 1e-12
            hi_p = bandpower(f, p[i], 30, 45) or 1e-12
            oneover_f = lo_p / hi_p

            txt, col = verdict(stds[i], mains_ratio, oneover_f)
            bars[i].set_width(stds[i])  # x-axis autoscales, so no cap
            bars[i].set_color(col)
            star = "* " if names[i] in OCCIPITAL else "  "
            oneover_s = ">999" if oneover_f > 999 else "%.1f" % oneover_f
            bar_texts[i].set_text("%s%.1f uV   %s   mains %.0f%%   1/f %s"
                                  % (star, stds[i], txt, 100 * mains_ratio, oneover_s))
            worst = max(worst, stds[i])
        if worst > ax_bar.get_xlim()[1]:
            ax_bar.set_xlim(0, min(worst * 1.15, 200))

        # ---- alpha test ---------------------------------------------------
        ph = state["phase"]
        if ph == "idle":
            occ = [i for i, n in enumerate(names) if n in OCCIPITAL]
            ok = sum(1 for i in occ if GOOD_LO <= stds[i] <= GOOD_HI)
            if occ:
                banner.set_text("%d/%d occipital channels in range   |   %s   |   "
                                "press A for the alpha test"
                                % (ok, len(occ),
                                   state["report"] or "mains %.0f Hz" % mains_hz))
                banner.set_color("#3f9e5a" if ok == len(occ) else "#333333")
            else:
                banner.set_text("no occipital channels on this montage   |   mains %.0f Hz"
                                % mains_hz)
                banner.set_color("#333333")
        else:
            elapsed = time.time() - state["t0"]
            remain = PHASE_SEC - elapsed
            if ph == "open":
                banner.set_text("ALPHA TEST -- keep eyes OPEN, look at the screen   %.0fs"
                                % max(0, remain))
                banner.set_color("#2b6cb0")
                if remain <= 0:
                    state["open"] = alphas.copy()
                    state.update(phase="closed", t0=time.time())
            elif ph == "closed":
                banner.set_text("ALPHA TEST -- CLOSE YOUR EYES now, stay relaxed   %.0fs"
                                % max(0, remain))
                banner.set_color("#7a4fb0")
                if remain <= 0:
                    state["closed"] = alphas.copy()
                    ratios = state["closed"] / np.maximum(state["open"], 1e-12)
                    occ = [i for i, n in enumerate(names) if n in OCCIPITAL]
                    parts, passes = [], 0
                    for i in occ:
                        good = ratios[i] >= 1.5
                        passes += good
                        parts.append("%s %.1fx%s" % (names[i], ratios[i],
                                                     "" if good else "!"))
                    state["report"] = ("alpha closed/open:  " + "   ".join(parts)
                                       + "   -> %d/%d pass" % (passes, len(occ)))
                    print("\n" + state["report"])
                    for i in range(n_ch):
                        print("   %-5s open %.3g  closed %.3g  ratio %.2fx"
                              % (names[i], state["open"][i], state["closed"][i], ratios[i]))
                    state["phase"] = "idle"

    if args.snapshot:
        for _ in range(6):   # let welch/autoscale settle
            update(None)
            time.sleep(0.4)
        fig.savefig(args.snapshot, dpi=110)
        print("wrote %s" % args.snapshot)
        try:
            eeg.board.stop_stream()
            eeg.board.release_session()
        except Exception:
            pass
        return 0

    from matplotlib.animation import FuncAnimation
    anim = FuncAnimation(fig, update, interval=100, cache_frame_data=False)

    print("\nDashboard open. Press A in the window for the alpha test, Q to quit.\n")
    try:
        plt.show()
    finally:
        try:
            eeg.board.stop_stream()
            eeg.board.release_session()
        except Exception:
            pass
        print("Closed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
