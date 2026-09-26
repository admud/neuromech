# NeuroMech Control — SSVEP BCI

Brain-computer interface control layer for NeuroMech. It reads EEG from an
8-channel **OpenBCI Cyton** and decodes where the user is looking using
**SSVEP** (steady-state visually evoked potentials). Four targets flicker at
different frequencies (up / down / left / right), and the decoder turns the
brain's response into a direction command.

Built on top of [EEG-ExPy](https://github.com/NeuroTechX/EEG-ExPy) (NeuroTechX),
which provides the device drivers (`eegnb`), experiments and analysis tools.
The upstream README is kept as [`EEG-ExPy_README.rst`](EEG-ExPy_README.rst).

**For driving the robot, use the hub** ([`../hub`](../hub/README.md), see the
[main README](../README.md)). It reuses `ssvep_bci.Decoder` from this folder
unchanged and adds the operator display, safety rules and the rover link.
The scripts here are the standalone tools: contact check, desktop test GUI,
calibration and evaluation.

## Setup

Requires **Python 3.10** (Windows tested).

```bash
cd control
py -3.10 -m venv .venv          # macOS/Linux: python3.10 -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

Plug in the Cyton USB dongle (switch on **GPIO6**) and turn the board on.
Its COM port varies between machines (COM6, COM8, ...; Device Manager → Ports,
"USB Serial Port"). `contact_viz.py` and the hub find it automatically; the
other scripts take `--port`. COM3/COM4-style "Standard Serial over Bluetooth"
ports are never the headset.

Electrodes that matter for SSVEP: **O1, O2, P7, P8** (occipital/parietal).

## Workflow

### 1. Check electrode contact

```bash
python contact_viz.py                  # live dashboard: traces, spectra, verdicts (port auto-detected)
python occipital_check.py COM8         # text readout, gated on O1/O2/P7/P8
```

In `contact_viz.py` press **A** for the alpha test (8 s eyes open, then 8 s
eyes closed). Occipital alpha should jump when your eyes close. If it does, the
electrodes are really on your scalp. Target per-channel stdev is 1–9 µV.

A clean recording on our laptop measured 3–4 µV of EEG noise per channel
with a small 50 Hz peak. If every channel shows a big 50 Hz line, reseat the
ear clips (reference/ground) and **unplug the laptop charger**; that
recording was unusable until both were fixed.

### 2. Try the live BCI (no calibration needed)

```bash
python ssvep_bci.py --port COM8
python ssvep_bci.py --device synthetic   # no headset: test the GUI only
```

Look at a flickering target to move the cursor.
Keys: `ESC` quit · `SPACE` recentre · `D` debug readout.

Useful options: `--freqs 11,14,17,20` (up,down,left,right, in Hz), `--window 3.0`
(decode window in seconds), `--margin`, `--speed`, `--windowed`.

### 3. Record and evaluate (~6 min)

```bash
python ssvep_calibrate.py --port COM8 --blocks 12 --trial-len 5 --out calib_s1.npz
python ssvep_eval.py calib_s1.npz                    # one onset-aligned window per trial (optimistic)
python ssvep_eval_live.py calib_s1.npz --window 2    # replayed the way the hub drives (realistic)
```

`ssvep_eval.py` runs leave-one-block-out cross-validation for each decoder and
window length, with accuracy and information transfer rate (bits/min).

`ssvep_eval_live.py` replays the recording like live use: trials joined as
gaze switches, a window sliding every 0.25 s, and the hub's margin + dwell
rules. It reports the share of time the robot would move the right way, the
**wrong** way, or stay idle, and how long it takes to respond after a gaze
switch. `--notch 0 --fmax 50` evaluates exactly the decoder as it runs today.

What our recordings showed:
- **Plain CCA beat the trained models** (`trca_cca`, `trca`) on every
  recording, so the hub runs without `--model`.
- **A 2 s window** was the sweet spot: 94% per window, and in the live replay
  (`ssvep_eval_live.py` defaults) about 65% of the time moving the right way and 9% the wrong way, with about
  1.9 s to respond. 3 s responds slower and makes more wrong moves after a
  gaze switch.
- **Keep 11/14/17/20 Hz**: 11/13/15/17.5 Hz decoded much worse for our
  operator (13–15 Hz gave a weak response).

A trained model can still be tried with
`python ssvep_bci.py --port COM8 --model calib_s1.npz --mode trca_cca` (or the
hub's `--model`), but check it against plain CCA with `ssvep_eval_live.py`
first.

## Decoders

| Mode       | Training | Notes |
|------------|----------|-------|
| `cca`      | none     | Filter-bank CCA against sin/cos templates. Default without `--model`. |
| `trca_cca` | calib    | TRCA-learned spatial filter plus phase-invariant CCA matching. Best default with a model. |
| `trca`     | calib    | Full ensemble TRCA with per-user templates. Strongest in the literature, but phase-dependent. |

References: Chen et al. 2015 (FBCCA), Nakanishi et al. 2018 (TRCA).

## Files

| File | Purpose |
|------|---------|
| `ssvep_bci.py` | Live 4-target SSVEP cursor-control GUI |
| `ssvep_calibrate.py` | Collect cued, phase-aligned calibration trials → `.npz` |
| `ssvep_trca.py` | Decoder library (CCA, TRCA-CCA, TRCA) |
| `ssvep_eval.py` | Offline cross-validated decoder comparison + ITR |
| `ssvep_eval_live.py` | Replays a calibration file the way the hub drives: sliding windows, gaze switches, margin + dwell; reports correct / wrong / idle time. Notches 50 Hz mains by default |
| `run_ssvep.py` | Run EEG-ExPy's standard visual SSVEP experiment on the Cyton |
| `ssvep_check.py` | PSD/SNR plot of a `run_ssvep.py` recording |
| `occipital_check.py` | Terminal signal-quality monitor for O1/O2/P7/P8 |
| `contact_viz.py` | Live electrode-contact dashboard with alpha test |
| `fake_calib.npz` | Synthetic calibration file for testing `ssvep_eval.py` / `--model` |
| `eegnb/`, `examples/`, `doc/`, … | Upstream EEG-ExPy |

## License

EEG-ExPy is BSD-3-Clause licensed. See [`LICENSE`](LICENSE).
