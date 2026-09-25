# NeuroMech Control — SSVEP BCI

Brain-computer interface control layer for NeuroMech. It reads EEG from an
8-channel **OpenBCI Cyton** and decodes where the user is looking using
**SSVEP** (steady-state visually evoked potentials). Four targets flicker at
different frequencies (up / down / left / right), and the decoder turns the
brain's response into a direction command.

Built on top of [EEG-ExPy](https://github.com/NeuroTechX/EEG-ExPy) (NeuroTechX),
which provides the device drivers (`eegnb`), experiments and analysis tools.
The upstream README is kept as [`EEG-ExPy_README.rst`](EEG-ExPy_README.rst).

## Setup

Requires **Python 3.10** (Windows tested).

```bash
cd control
py -3.10 -m venv .venv          # macOS/Linux: python3.10 -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

Plug in the Cyton USB dongle and note its serial port (default `COM11`, check
Device Manager → Ports). Every script takes `--port`.

Electrodes that matter for SSVEP: **O1, O2, P7, P8** (occipital/parietal).

## Workflow

### 1. Check electrode contact

```bash
python occipital_check.py COM11        # text readout, gated on O1/O2/P7/P8
python contact_viz.py --port COM11     # live dashboard: traces, spectra, verdicts
```

In `contact_viz.py` press **A** for the alpha test (8 s eyes open, then 8 s
eyes closed). Occipital alpha should jump when your eyes close. If it does, the
electrodes are really on your scalp. Target per-channel stdev is 1–9 µV.

### 2. Try the live BCI (no calibration needed)

```bash
python ssvep_bci.py --port COM11
python ssvep_bci.py --device synthetic   # no headset: test the GUI only
```

Look at a flickering target to move the cursor.
Keys: `ESC` quit · `SPACE` recentre · `D` debug readout.

Useful options: `--freqs 11,14,17,20` (up,down,left,right, in Hz), `--window 3.0`
(decode window in seconds), `--margin`, `--speed`, `--windowed`.

### 3. Calibrate for better accuracy (~4 min)

```bash
python ssvep_calibrate.py --port COM11 --blocks 6 --out calib_s1.npz
python ssvep_eval.py calib_s1.npz
python ssvep_bci.py --port COM11 --model calib_s1.npz --mode trca_cca
```

`ssvep_eval.py` runs leave-one-block-out cross-validation for each decoder and
window length. It reports accuracy and information transfer rate (bits/min),
which tells you which `--mode` and `--window` to run with.

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
