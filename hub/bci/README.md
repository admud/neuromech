# hub/bci: EEG engine, arbiter and jaw clench

This is everything between the headset and the velocity command.

- `board.py`: opens the Cyton, brainflow's synthetic board, or our fake
  EEG (`--device sim`).
  - `find_openbci_port()` auto-detects the dongle (the FTDI chip).
  - It never lets eegnb prompt for a port, which would hang the hub.
  - Decoding channels: **O1, O2, P7, P8**.
- `engine.py`: `BciEngine`.
  - Runs `control/ssvep_bci.Decoder` (filter-bank CCA), unchanged, every
    0.25 s on the last `window` seconds of EEG.
  - Feeds each decode to the arbiter exactly once.
  - Watches for EEG stalls.
  - Runs the clench detector every 50 ms.
- `arbiter.py`: turns decodes into a command.
  - **Margin:** the winner must beat the runner-up by at least this much.
  - **Dwell:** it must win this many decodes in a row.
  - Then the hold or latch rules below apply, with arming and override on
    top.
- `clench.py`: the jaw-clench detector.
- `record_clench.py`: a guided clench recording, plus threshold analysis.
- `config.py`: `EngineSettings` (the defaults behind the hub's CLI flags).

## Control modes

**Hold** (default, `--control hold`):
- The rover drives while the same circle keeps winning.
- It stops as soon as the winner changes or disappears. That takes about
  2 s after you look away, because the decode window still holds the old
  flicker.

**Latch** (`--control latch`): select with your eyes, confirm with your jaw.
1. Gaze only **previews**: the winning circle gets an amber ring, and the
   rover gets zero velocity.
2. A **clench latches the direction you'd been looking at in the 0.5 s
   before the clench**. The clench's muscle signal scrambles the EEG, so
   decodes made during it are never used. With no such direction, the
   clench is ignored and shows "NO TARGET".
3. The rover keeps going while you look anywhere.
4. **A second clench always stops it.**
5. **The latch also releases** on STOP, any disarm, a mode change, or
   `--latch-max` seconds (default 3).
6. Keyboard override (arrows) beats everything while held.

## Jaw-clench detector (`clench.py`)

This is a port of the Muse detector (`blink_clench_v2.py`) to the Cyton at
250 Hz:
1. **50/100 Hz mains notch.** It's wide (45–55 and 90–110 Hz), because a
   narrow notch let mains ramps through.
2. 30 Hz high-pass.
3. Teager-Kaiser energy, smoothed into an envelope.
4. Robust z-score against a rolling calm baseline.
5. Channels **Fp1, Fp2, P7, P8**, combined by the second-highest score, so
   one bad electrode can't trigger it.
6. It fires **once per clench** (it must drop back below threshold first),
   with a 50 ms minimum duration and a 0.4 s refractory period. Leave
   about 1 s between clenches.

**Tuning the threshold on your own clenches** (with the hub stopped):
```
control\.venv\Scripts\python -m hub.bci.record_clench --out clench_s1.npz
control\.venv\Scripts\python -m hub.bci.record_clench analyze clench_s1.npz
```
The recording takes about 2 minutes: rest, 10 cued clenches, clenching
while looking at the screen edges, and blinking with no clenches (the
false-alarm check). `analyze` prints clench-vs-rest scores, a suggested
threshold, and detections and false alarms per minute. Pass the value as
`--clench-threshold`, or set it live on the dashboard.

## Decoding: how to judge a recording

Record with `control/ssvep_calibrate.py`, then run:
```
control\.venv\Scripts\python control\ssvep_eval_live.py calib.npz --window 2
```
It replays the recording the way this engine drives (sliding windows,
margin, dwell). It reports how often the robot would move the right way,
the wrong way, or not at all, and how long it takes to respond after a
gaze switch.
