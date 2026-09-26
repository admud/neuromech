# hub.gui: desktop operator display (Phase 4)

A native psychopy window on the laptop's 120 Hz panel. It shows the robot's
video full screen with four SSVEP circles on top (top = forward, bottom =
back, left, right). The hub sees it as the phone (`/ws/phone`, with
`hello.client = "desktop"`), so the hub, the engine and the safety rules
are unchanged. Brief: [plan/phases/4-desktop-gui.md](../../plan/phases/4-desktop-gui.md).

## Run (from the repo root)

```
control\.venv\Scripts\python -m hub --device sim            # or real headset: python -m hub
control\.venv\Scripts\python -m hub.sim.robot_sim --video test --fps 20
control\.venv\Scripts\python -m hub.gui                     # full screen on screen 0
control\.venv\Scripts\python -m hub.gui --screen 1          # screens are listed at startup
control\.venv\Scripts\python -m hub.gui --windowed --duration 30 --log-frames frames.csv
control\.venv\Scripts\python -m hub.gui.analyze frames.csv  # timing + measured frequencies
```

Options: `--hub host:port` (default `127.0.0.1:8765`), `--screen N`,
`--windowed` / `--win-size 1280x720`, `--size 0.16` (circle diameter as a
fraction of the short side), `--no-video`, `--log-frames FILE`,
`--duration S`. At startup it prints the screens, the window size and the
refresh rate psychopy measures. It warns if that is below 100 Hz. At exit it
prints frames, fps, late frames and video counts.

Keys: **Space/Esc = STOP**, **hold Enter 1 s = ARM** (a progress bar shows),
arrows/WASD = drive while armed (sent as a dashboard `override`),
**F** = timing overlay, **Q** = STOP then quit. Minimising sends STOP.
Closing the window (X) just disconnects, so the hub disarms with
`phone_lost`. Losing focus drops held keys.

## Files

- `app.py`: window, render loop, keys. The loop:
  1. `t = win.getFutureFlipTime()`;
  2. levels `0.5*(1+sin(2*pi*f*t))`;
  3. upload the newest decoded video frame to a GL texture if it changed;
  4. draw video, then the circles (raw GL: a dark ring, then the disc), then the HUD;
  5. flip.
- `net.py`: `HubClient`, an asyncio thread with three links:
  - `/ws/phone`: hello, ping every 2 s, frame_stats every 1 s, arm;
  - `/ws/dashboard`: override only;
  - `/ws/video`.
  All three reconnect every 1 s. Phone and dashboard links are dropped
  after 2.5 s of silence (half-open sockets).
- `video.py`: `VideoDecoder`, a thread that keeps only the newest JPEG and
  decodes it with `cv2.imdecode` (which releases the GIL).
- `hud.py`: static overlays: ARMED/DISARMED + reason, winner ring, command
  arrow (green bci, blue override), status line, DISCONNECTED banner, arm
  bar, timing overlay.
- `logic.py`: window-free logic (levels, layout, frame stats, ArmHold,
  DriveKeys, OverrideSender, FrameLog). `analyze.py`: offline log check.
- Tests: `hub/tests/test_gui_logic.py`, `hub/tests/test_gui_net.py` (fake hub).

## Frame log (`--log-frames`)

CSV, one row per flip: `frame, t_pred, t_flip, L_up..L_right, f_up..f_right`.
- `t_pred` is the predicted flip time the levels were computed for.
- `t_flip` is the time `win.flip()` returned.
- `L_*` are the levels drawn (0..1).
- `f_*` are the frequencies in force at that frame, so live changes can be analysed.

It's kept in memory and written at exit.

`analyze` reports:
- fps, p95, max, late frames (> 1.5x the median interval);
- the p95 prediction error `|t_flip - t_pred|`;
- for each stretch of constant frequencies, the frequency each target
  measures against the **real flip times** (a DFT peak search). It flags a
  MISMATCH beyond 0.05 Hz and exits 1.

## Handoff notes (opus, 2026-09-26)

Everything below was measured **windowed (1280x720) on the built-in panel**,
against my own `hub --device sim` on port 18777 plus
`robot_sim --video test --fps 20`. Other agents were using the laptop at the
same time. Full screen wasn't run, because windows open on the user's
screen. psychopy measured 116.7–120.0 Hz windowed. Screen 0 reports
2560x1440, so psychopy is DPI-aware and the window is in physical pixels.

**Timing**
- 30 s with video: 3601 frames, **120.02 fps, 0 late, max 9.7 ms**, p95 8.82 ms.
  Prediction error p95 0.61 ms. All 479 frames that arrived were decoded,
  none dropped. (`robot_sim` delivers ~16 fps even with `--fps 20`.)
- Other 12–30 s runs: 0.06–0.51% late.
- Longer runs:
  - The 23 s scripted run below was 0.51% late by the app's count
    (hidden time excluded).
  - `analyze` counts 1.27% on the same log, because it includes the
    scripted 0.5 s minimise, when the loop idles on purpose.
- Fixed along the way:
  - psychopy `TextStim` re-rendering (~2.7 ms per change) made one frame late
    every second (1.4–2.1%). The HUD now uses pyglet Labels (~0.6 ms), and every
    glyph is rasterised once at startup.
  - GL state: psychopy leaves texture unit 1 active, and pyglet labels leave
    texturing on. With no video this turned the circles black. The video and
    circle code now reset texture unit 0, texturing and the shader program
    explicitly.

**Frequencies:** from the logged real flips, 11.00/14.00/17.00/20.00 Hz in
every run. A live `set_config` from the dashboard (up 11 → 12) measured
12.00/14.00/17.00/20.00 after the change.

**Scripted end-to-end run** (`hub --device sim`; synthetic key events, plus
a dashboard observer sending `sim_gaze` and `set_config`):
- An Enter hold of 0.5 s does not arm; 1.2 s arms.
- `sim_gaze up`: command `up/bci`, robot vx +0.30, x from 0 to 0.97 m.
- Held Left: command `left/override`, robot vy +0.30 (left is +y).
- Space → `user`. Minimise → STOP (`user`). Close while armed → `phone_lost`.
- Q: ARM → STOP (`user`) → disconnect.
- Hub killed for 8 s: the DISCONNECTED banner showed, the circles kept
  flickering, and the GUI reconnected by itself when the hub came back.

**Tests:** `pytest hub/tests`: 71 passed (14 new, in `test_gui_*`).

**For @main:**
- Full-screen timing on the 120 Hz panel still needs your run. Start with
  `python -m hub.gui --log-frames f.csv --duration 60`, then run `analyze`.
- `CLAUDE.md` should list `hub/gui/` in the repo map and in Run. I left
  that file alone because it's outside my scope.
- In the sim, with gaze `none`, the engine sometimes still decodes a winner
  (I saw `left` briefly). That's the known creeping behaviour noted in
  CLAUDE.md, not the GUI.

## Phase 6: latch mode (opus, 2026-09-26)

What the display shows, from the engine's optional state fields
`control_mode`, `latched`, `latch {elapsed_s, max_s, left_s}` and
`clench {z, threshold, count, fired_at, last {t, result, direction}}`. It
also accepts the first proposal's `latched_at` / `clench.ignored_at`.

**GUI (`hub.gui`)**
- All latch and clench text sits in the **top-left margin** under
  ARMED/DISARMED, off the video (the user asked for it not to cover the feed).
- In latch mode with nothing latched, the gaze winner gets an **amber** ring
  and a small "PREVIEW": selected, but not moving. In hold mode the ring
  stays green, as before.
- Latched: a small **"LATCHED ▲/▼/◄/►"** and a thin timer bar under it that drains over
  `latch.max_s`. The bar is interpolated between the 10 Hz states from
  `left_s` and state age. The ring moves to the latched target, and the
  command arrow shows the direction being driven.
- Any clench flashes a small **CLENCH** (or **NO TARGET** / **NOT ARMED**) in the same margin for 0.4 s.
- `result == "no_target"` shows "no target - look at a circle, then clench"
  for 1.5 s, and `not_armed` shows "clench ignored - not armed". Events
  are detected by a change of `clench.last.t`, so an old event seen on
  connect never flashes.
- The status line shows `mode hold|latch`.
- Timing: every label, ring set (green and amber) and rect is created and
  drawn once at startup. Swapping a label's text or recolouring a
  psychopy ring mid-run cost late frames (up to 38 ms), so a state change
  now costs nothing. The logic is `logic.LatchView`, which is unit-tested.
- `--log-frames` has a new `work_ms` column: this thread's CPU time per
  frame. `analyze` prints its p95 and max. With small `work_ms`, late frames
  come from outside the GUI.

**Dashboard (`web/dashboard/`)**, a new **Control** panel:
- HOLD / LATCH toggle (`set_config control_mode`), the latched state, with
  seconds left and a timer bar;
- clench z meter, with the threshold marked, a count and the last result;
- threshold slider (`set_config clench_threshold`, sent on release; shows
  "applied" when the hub echoes it);
- max latch (`set_config latch_max_s`);
- "no target" / "not armed" notices;
- a **sim clench** button and **K** key (sim only).

The header's command box says LATCHED. A hub without these fields hides the
panel's controls. `?demo=1` emulates latch mode in the engine's field shape.

**Measured**
- Against opus3's engine (`hub --device sim --control latch`, from the
  working tree before it was committed) plus `robot_sim --fps 20`, with the
  GUI windowed and a dashboard client scripting `sim_gaze` / `sim_clench`:
  - clench with no gaze → `no_target`;
  - gaze up, then clench → latched up (the robot drove +x while the gaze
    wandered to left);
  - clench → `unlatched`;
  - re-latch → released by the timeout 2.97 s later;
  - re-latch → Space → disarm `user`, latch released.
- GUI timing through that whole 24 s sequence: **119.97 fps, 1 late frame
  (0.03%)**, max 16.5 ms, our work per frame p95 1.35 ms. Frequencies
  measured 11/14/17/20 Hz.
- Earlier noisy runs (1–18% late for *both* the Phase 4 and Phase 6 code)
  came from an orphaned headless Chrome of my own tests using 42% of the
  GPU. It was killed, and the test helper now kills the whole process tree.
- Dashboard (CDP, real engine): mode toggle, no-target notice, latch +
  timer, threshold 10 and max latch 4 applied and echoed. In `?demo=1`:
  every path, including timeout and STOP releasing the latch.

**Note for the engine:** two `sim_clench`es less than ~0.9 s apart count as
one (0.6 s burst + 0.4 s refractory: 0.5 and 0.7 s gaps gave 1 of 2; 0.9 s
and more gave 2 of 2). So "clench to stop" right after latching needs a
~1 s gap in sim. Real clenches may differ.

## Rover video freeze (@main, 2026-09-26)

- The rover's camera browns out while the motors run.
- The bridge (`hub.ugv`) then re-sends the last frame from before the drive
  at the normal rate, and sets `video_frozen` in its telemetry.
- **The display doesn't mark it** (the user's choice). A FROZEN badge was
  tried and removed. `video_frozen` is there if one is wanted later.
