# Phase 6: jaw-clench latch ("select with your eyes, confirm with your jaw")

**Status:** approved 2026-09-26, in progress · **Agents:** opus3 (engine), opus (GUI + dashboard) · **Tests:** @main

**User decisions (2026-09-26):**
1. Latch mode: gaze only **previews** until a clench.
2. A clench while latched **always stops**.
3. **Maximum latch time 3 s by default, adjustable** (`latch_max_s`, dashboard + CLI).
4. Default mode: **"hold"** for now (backward compatible). `--control latch` or
   the dashboard switches; the user can make latch the default later.
5. The user will record clench data with the recorder, so land it first.

## The idea
Today a direction only drives while you keep looking at its circle, and it
stops about 2 s after you look away. The new **latch mode**:
1. **Look at a circle.** The decoder highlights it (ring + arrow) but the
   rover does **not** move yet.
2. **Clench your jaw.** The highlighted direction **latches**: the rover
   keeps going that way on its own, and you're free to look at anything.
3. **Clench again.** It unlatches and stops.

The existing mode ("hold") stays, and you choose between them on the
dashboard or with a CLI flag.

**Why it's workable**
- A jaw clench makes a huge burst of high-frequency muscle signal (EMG,
  above 30 Hz) on every scalp channel, most on the frontal and temporal
  ones. It's far easier to detect than an SSVEP.
- The user's Muse detector (`blink_clench_v2.py`) measured about **50x
  separation** between clenches and rest with this method.
- Stopping becomes a clench (about 0.2–0.5 s) instead of the 2 s look-away
  lag.
- False moves from gaze noise disappear: gaze alone never moves the rover,
  so it needs a gaze winner **and** a clench.

## Detection (port of the Muse detector to the Cyton)
Method: the one in `Muse2Demo/.../classifiers/blink_clench_v2.py`.
1. **50 Hz (and 100 Hz) notch first.** The Cyton recordings carry mains,
   which would otherwise dominate anything above 30 Hz.
2. High-pass at 30 Hz, 4th order.
3. Teager-Kaiser energy (TKEO) per sample, smoothed into an envelope.
4. Robust z-score (median/MAD over a rolling baseline that only updates
   while calm).
5. The clench fires when the channel-combined z stays above the threshold
   for **at least 50 ms**, followed by a **0.4 s refractory** period.

Cyton specifics:
- 250 Hz.
- Channels **Fp1, Fp2, P7, P8** by default (strongest EMG). Configurable.
  O1/O2 stay SSVEP-only.
- It runs in the engine loop every 50 ms on the new samples since the
  last pass (vectorised), not on the 2–3 s decode window, so detection
  latency is about 50–100 ms.

## Control logic (arbiter, latch mode)
- **Unlatched:** the decoder runs as today and its winner is shown, but
  velocity is zero.
- **Clench while unlatched:** latch the **last dwelled winner from just
  before the clench** (within the previous 0.5 s). The clench's own EMG
  corrupts the EEG for about 0.5 s, so the decode during the clench is
  never used. No valid winner means the clench is ignored, and the GUI
  shows "no target".
- **Clench while latched:** unlatch and stop.
- **Also unlatch on:** STOP (Space/Esc, phone, dashboard), disarm, any
  auto-disarm (phone/robot/EEG lost), and a **maximum latch time**
  (default **3 s**, configurable) as a safety net.
- **Keyboard override** still wins over everything while held.

## Protocol additions (optional fields only; nothing renamed)
- `state.control_mode`: `"hold"` or `"latch"`.
- `state.latched`: a direction or `null`.
- `state.clench`: `{z, fired_at, count}` for display and tuning.
- `set_config`: adds `control_mode`, `clench_threshold` and `latch_max_s`.
- `sim_clench`: dashboard only, `--device sim` only. It injects a clench
  burst into the fake EEG.
- CLI: `python -m hub --control latch --clench-threshold 8`.

## Work split (parallel)
**opus3 (engine side):** `hub/bci/clench.py`, the engine and arbiter
changes, protocol fields, `SimSSVEPBoard` clench injection, and tests.
Plus a small recorder,
`python -m hub.bci.record_clench --port COM8 --out clench_s1.npz`. It
prompts the user through 20 s rest, 10 cued clenches, and 20 s of looking
at the targets while clenching, and saves the raw 8 channels plus markers.
An offline `analyze` reports the z of clenches against rest and suggests a
threshold.

**opus (display side):**
- **GUI:** a big "LATCHED ▲" indicator, a clench flash, "no target" when a
  clench found nothing to latch, and a latch timer bar.
- **Dashboard:** a mode toggle, the clench z meter and threshold slider,
  the latched state, and a "sim clench" button in sim mode.

## Tests (@main)
- **Unit:** the detector on synthetic EMG bursts versus EEG and 50 Hz. The
  arbiter's latch/unlatch/timeout/STOP paths.
- **Sim end to end:** gaze up plus sim clench → rover `FWD` continuously
  while gaze wanders. Clench → `STOP`. Timeout, Space and disarm all
  release the latch.
- **Real data:** the user's `clench_s1.npz` → detection rate and false
  alarms per minute at the chosen threshold, and a check that looking and
  blinking don't trigger it.

## Open questions (need the user's answers)
1. In latch mode, should gaze **alone** still move the rover (as now), or
   only preview until the clench? Recommendation: preview only.
2. While latched, should a clench always stop, or should clenching while
   looking at a *different* circle switch direction? Recommendation: always
   stop; it's simpler and more predictable.
3. Is a 10 s maximum latch time OK as a safety net?
4. Default mode: keep "hold" as the default, with latch switched on from
   the dashboard or CLI?
5. Can you do a 2-minute clench recording with the Cyton (the recorder
   guides you) so the threshold is tuned on your real data?
