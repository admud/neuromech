"""Quick-look SSVEP analysis for the Cyton montage (adapted from
examples/visual_ssvep/01r__ssvep_viz.py, which assumes a 5-channel Muse)."""
import os, sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mne import Epochs, find_events

from eegnb.analysis.analysis_utils import load_data

DATA_DIR = os.path.join(os.path.expanduser("~/"), ".eegnb", "data")
OUT = sys.argv[1] if len(sys.argv) > 1 else "ssvep_check.png"

raw = load_data(subject=1, session=1, experiment="visual-SSVEP",
                site="local", device_name="cyton", data_dir=DATA_DIR)
print(raw.info)
print("channels:", raw.ch_names)

raw.filter(1, 45, method="iir")

events = find_events(raw)
event_id = {"30 Hz": 1, "20 Hz": 2}
epochs = Epochs(raw, events=events, event_id=event_id, tmin=-0.5, tmax=3.0,
                baseline=None, preload=True, verbose=False)
print(epochs)

welch = dict(method="welch", n_fft=1028, n_per_seg=256 * 3, picks="all", fmin=1, fmax=45)
psd30, f30 = epochs["30 Hz"].compute_psd(**welch).get_data(return_freqs=True)
psd20, f20 = epochs["20 Hz"].compute_psd(**welch).get_data(return_freqs=True)
psd30 = 10 * np.log10(psd30).mean(0)
psd20 = 10 * np.log10(psd20).mean(0)

names = epochs.ch_names
occ = [names.index(c) for c in ["O1", "O2", "P7", "P8"] if c in names]

fig, axs = plt.subplots(len(occ) + 1, 1, figsize=(10, 3 * (len(occ) + 1)), sharex=True)
for ax, ci in zip(axs, occ):
    ax.plot(f30, psd30[ci], color="b", label="30 Hz stim")
    ax.plot(f20, psd20[ci], color="r", label="20 Hz stim")
    for fq, c in [(20, "r"), (30, "b")]:
        ax.axvline(fq, color=c, ls=":", alpha=0.6)
    ax.set_title(names[ci]); ax.set_ylabel("PSD (dB)"); ax.legend(fontsize=8)

axs[-1].plot(f30, psd30[occ].mean(0), color="b", label="30 Hz stim")
axs[-1].plot(f20, psd20[occ].mean(0), color="r", label="20 Hz stim")
for fq, c in [(20, "r"), (30, "b")]:
    axs[-1].axvline(fq, color=c, ls=":", alpha=0.6)
axs[-1].set_title("occipital mean"); axs[-1].set_xlabel("Frequency (Hz)")
axs[-1].set_ylabel("PSD (dB)"); axs[-1].legend(fontsize=8)
plt.tight_layout(); plt.savefig(OUT, dpi=110)
print("saved", OUT)

# Quantify: power at each stimulus frequency relative to neighbouring bins.
def snr(psd, freqs, f0, halfwidth=0.5, noise=(2, 5)):
    sig = psd[(freqs > f0 - halfwidth) & (freqs < f0 + halfwidth)].mean()
    nb = psd[((freqs > f0 - noise[1]) & (freqs < f0 - noise[0])) |
             ((freqs > f0 + noise[0]) & (freqs < f0 + noise[1]))].mean()
    return sig - nb

print("\nSNR in dB at each stimulus frequency (signal minus neighbouring bins):")
print(f"{'chan':>6} {'30Hz@30':>9} {'20Hz@20':>9}   {'30Hz@20':>9} {'20Hz@30':>9}")
for ci in occ:
    print(f"{names[ci]:>6} {snr(psd30[ci],f30,30):9.2f} {snr(psd20[ci],f20,20):9.2f}   "
          f"{snr(psd30[ci],f30,20):9.2f} {snr(psd20[ci],f20,30):9.2f}")
print("\nFirst two columns = response to its own stimulus (want clearly positive).")
print("Last two = cross-check; should be lower than the matching column.")
