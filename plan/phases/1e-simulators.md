# Phase 1E: simulators

**Agent:** opus3 · **Runs:** Phase 1, in parallel with 1A–1D

## Goal
Make the whole loop testable with no headset and no robot:
1. an EEG board that fakes a user looking at a chosen target, and
2. a robot client that behaves exactly like the RPi will, and becomes its template.

## Read first
- [../protocol.md](../protocol.md): `SimSSVEPBoard` interface, `/ws/robot`, the robot watchdog rule
- `control/ssvep_bci.py`: `Decoder` (what your board must satisfy) and `reference_bank`
- [../README.md](../README.md#rules-for-every-agent): git and environment rules

## You own
`hub/sim/__init__.py`, `hub/sim/sim_board.py`, `hub/sim/robot_sim.py`,
`hub/tests/test_sim_board.py`, `hub/tests/test_robot_sim.py`

## Build

1. **`sim_board.py`: `SimSSVEPBoard`**, exactly the interface in protocol.md.
   - **Real-time:** samples are generated from the monotonic clock at `fs`
     (250). `get_current_board_data(n)` returns the newest `n` samples as
     `(n_rows, n)`, EEG in µV on rows 1–8, row 0 a sample counter. Keep
     ~10 s of history. Generate from the absolute sample index so phase is
     continuous across calls.
   - **Signal:**
     - background: 1/f-ish noise (~10 µV rms) + a 10 Hz alpha component +
       small 50 Hz line noise;
     - while gazing at target *i*: a sinusoid at `freqs[i]` plus 2nd and 3rd
       harmonics, strongest on O1/O2, weaker on P7/P8, faint elsewhere
       (Cyton order: Fp1 Fp2 C3 C4 P7 P8 O1 O2), amplitude scaled by `snr`.
   - Gaze changes take effect at the moment they're made. The decoder's
     window then holds a realistic mix, so the latency is realistic.
   - Thread-safe: the decoder thread reads while the engine calls `set_gaze`/`set_freqs`.
   - **Tune the default `snr`** so it's realistic but reliable (see acceptance).

2. **`robot_sim.py`**:
   `python -m hub.sim.robot_sim [--hub ws://127.0.0.1:8765/ws/robot] [--video test|webcam] [--camera 0] [--fps 20] [--show]`
   - asyncio + the installed `websockets` 16 client
     (`websockets.asyncio.client.connect`). Reconnect with backoff.
   - On connect send `hello`. Send JPEG frames as binary
     (`cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])`),
     640x480, `--fps`.
   - **`test` video:** a top-down arena view with a grid, the robot as a
     circle (forward = up the screen, left = screen-left) and its trail. The
     HUD shows `vx`/`vy`, `seq`, watchdog state and a **wall clock with
     milliseconds**, so glass-to-glass latency can be read off a photo of
     the phone next to the laptop. The phone video then shows the robot
     moving in response to the BCI.
   - **`webcam` video:** camera frames with the same small HUD.
   - **Kinematics:** position += (vx, vy) · max_speed · dt, clamped to the
     arena. `vy` positive = left.
   - **Watchdog (mandatory):** no `cmd` within its `ttl_ms` → stop and report
     `watchdog_stopped: true`.
   - `telemetry` at 2 Hz (`vx`, `vy`, `watchdog_stopped`, `battery_v: null`,
     plus `x`, `y`). Reply `pong` to `ping`.
   - Headless by default; `--show` opens a cv2 window.
   - **Keep it portable to the Pi:** isolate `get_frame()` and
     `drive(vx, vy)` so the RPi port only swaps those two.

3. **Tests**
   - `test_sim_board.py`: feed `SimSSVEPBoard` to `ssvep_bci.Decoder`
     (window 3 s, margin 0.06). After 3 s of gaze at each target, the
     winner equals that target in >= 90% of decodes. With gaze None the
     winner is None in >= 80% of decodes. Frequency changes are respected.
     Keep the test under ~60 s total (a shorter window or fewer repeats is fine).
   - `test_robot_sim.py`: a throwaway `websockets.serve` server in the test
     receives `hello`, JPEG frames and telemetry. Sending `cmd` moves the
     robot the right way. Stopping `cmd`s triggers the watchdog within `ttl_ms`.

## Acceptance
- [ ] `SimSSVEPBoard` satisfies the protocol interface and works under the real `Decoder`
- [ ] Decoding accuracy targets above met with the default `snr`
- [ ] `robot_sim` runs against a test server now and against `python -m hub --stub` once 1A lands
- [ ] Watchdog stops the sim robot when commands stop
- [ ] `control/.venv/Scripts/python.exe -m pytest hub/tests/test_sim_board.py hub/tests/test_robot_sim.py` passes
- [ ] Handoff notes filled in, committed, @main tagged

## Handoff notes
_(fill in when done)_
