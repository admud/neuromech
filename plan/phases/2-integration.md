# Phase 2: integration, end-to-end test, runbook

**Agent:** opus3 (after finishing 1B) · **Runs:** after 1A–1F have all handed off and @main's reviews are fixed

## Goal
Turn six independently built pieces into one working system, prove the
full loop in simulation, and leave the user a demo-day runbook for the one
real-hardware test (headset + iPhone). You now own **every file**; keep
[../protocol.md](../protocol.md) in sync with anything you change.

## Read first
- [../README.md](../README.md), [../architecture.md](../architecture.md), [../protocol.md](../protocol.md)
- The *Handoff notes* at the bottom of every Phase 1 brief

## Do

1. **Bring it up in simulation** (repo root, venv python):
   `python -m hub --device sim`, then the dashboard (its embedded twin is the
   virtual robot) and the phone page in browser windows. Use a real iPhone on
   the same WiFi if one is reachable. Repeat the robot scenarios with
   `python -m hub.sim.robot_sim --video test` as the robot instead (dashboard
   Virtual robot switch OFF).

2. **Walk every scenario and fix what breaks.** Anywhere; you own all files.

   | # | Scenario | Expected |
   |---|---|---|
   | 1 | Fresh start | DISARMED (`startup`); robot gets zero `cmd`s at 10 Hz |
   | 2 | Arm, sim gaze up / down / left / right | Robot moves forward / back / **left** / **right**, both in the twin's third-person view and in the FPV feed on the phone. Check the signs. |
   | 3 | Sim gaze none | Robot stops. Note how long it takes. |
   | 4 | STOP from phone tap, dashboard button, Esc, Space | Disarms immediately |
   | 5 | Keyboard override while armed / disarmed | Moves only when armed; stops on release |
   | 6 | Kill robot sim while armed | `robot_lost`; reconnect stays disarmed |
   | 7 | Close phone page while armed | `phone_lost` |
   | 8 | Freeze the hub (e.g. suspend it) | Sim robot's watchdog stops it within `ttl_ms` |
   | 9 | Change freqs on dashboard | Phone flicker changes; decoder follows; sim gaze still decodes |
   | 10 | `--device synthetic` | Runs; no false driving beyond margin noise |
   | 11 | `--device cyton` with no dongle | Clear error listing ports; no prompt, no hang |
   | 12 | Drive the virtual robot into a wall | Stops and slides at walls, `collision` in telemetry; wheels spin the right way for each direction |
   | 13 | Esc / Space while the twin iframe has focus | STOP still works |
   | 14 | Virtual robot switch OFF with `robot_sim` running; full-screen button with it ON | Only one robot on `/ws/robot` at a time; full screen keeps the sim running |

3. **Measure and record** in the runbook: phone fps and p95 with video on
   (desktop browser, plus iPhone if available); video glass-to-glass latency
   from the sim robot's clock overlay; gaze-to-motion and look-away-to-stop
   times in sim; hub CPU.

4. **Review the two critical pieces with fresh eyes:** the phone flicker
   timing (1C) and the arbiter/safety rules (1B). Fix, don't just note.
   Keep screenshots to a minimum; check behaviour through logs, `state`
   messages and tests where you can.

5. **Write `plan/runbook.md`**: the demo-day procedure for the user's
   hardware test.
   - Setup: plug in the dongle; check contact with `control/contact_viz.py`
     (auto-detected port); start the hub.
   - Network: Windows Firewall (Public networks); iPhone Safari settings
     (60 fps flag, Low Power off, Auto-Lock never, brightness).
   - Phone: open the URL, Add to Home Screen, check the fps readout.
   - Drive: arm, drive, stop.
   - Fallbacks: iPhone Personal Hotspot if the WiFi blocks device-to-device
     traffic; `--port COMx` if auto-detect fails.
   - A troubleshooting table.

6. **Update docs to match reality:** `CLAUDE.md` (repo map, run commands,
   status), root `README.md` (layout), `plan/README.md` status table.

7. **Run the full test suite:** `control/.venv/Scripts/python.exe -m pytest hub/tests`.
   Then commit (you may commit any path now; still no push, no history
   rewrites) and tag @main with results and anything the user must know
   before testing.

## Acceptance
- [x] Scenarios 1–14 pass (or each exception is written up with a reason)
- [x] Measurements recorded in the runbook
- [x] `plan/runbook.md` lets the user run the hardware test without asking anyone
- [x] `CLAUDE.md`, `README.md`, `plan/README.md` match the code
- [x] All tests pass

## Handoff notes

**Scenarios** (all in simulation; `--device sim`, virtual robot in the dashboard unless stated)
- 1–7, 11–13: re-run with @main's `integration.mjs`, 20/20 pass. 11 was already checked by @main and hasn't changed.
- 8, frozen hub (process suspended with `DebugActiveProcess`, not killed):
  - `robot_sim` stops 0.49 s in, the virtual robot 0.44 s in.
  - **Bug fixed:** the hub came back **armed** after a 6 s freeze. The sim board caught up before any
    stall check, so the EEG looked fresh. The engine now treats a >1.5 s gap in its own loop as
    `eeg_stall`, with a test.
  - `robot_sim` (the Pi template) now runs its watchdog as a separate task, so a send blocked by a
    stalled hub can't delay the motor stop. Also tested.
- 9: new freqs from the dashboard form.
  - `config_id` bumps and the phone's `flicker.freqs` switch.
  - Measured on-screen flicker is exactly 11.5/13.5/16.5/19.5 Hz.
  - Sim gaze right/up decodes at the new freqs.
- 10, `--device synthetic`: **exception.** It drives "right" ~99% of the time. brainflow's synthetic
  board is a pure sine at 5 Hz × channel (C4 = 20 Hz), so that's expected, not a decoder fault. The
  engine now adds a `warnings` entry saying so. Use `--device sim` for behaviour.
- 14: Virtual robot switch OFF + `robot_sim`: only `sim` on `/ws/robot`.
  - Switch ON while `robot_sim` runs: one exchange, then the twin backs off. The hub now closes a
    replaced robot with 4001 "replaced" (protocol.md updated), so this takes ~0.5 s instead of ~3.5 s.
  - Full screen (with the switch ON): still `virtual`, 20 fps, drives.

**Other fixes**
- Hub default `--margin` 0.08 (CLI, `EngineSettings`, stub, protocol.md, dashboard demo).
- Video relay: never sends a frame older than 1 s. A new viewer was getting a 139 s old frame from a
  robot that had gone, which looks like a live feed. Test added.
- `control/contact_viz.py`: auto-detects the dongle when `--port` is omitted (reuses
  `hub.bci.board.find_openbci_port`).

**Added**
- `plan/runbook.md`: setup, drive, fallbacks, troubleshooting, measurements.
- `e2e/`: @main's scripts plus the Phase 2 ones (`freeze_twin.mjs`, `freeze_robot_sim.py`,
  `s9_freqs.mjs`, `s14_switch.mjs`, `measure.py`, `load_measure.mjs`), made path-independent.
- Docs: `CLAUDE.md` (status, map, run, gotchas), `README.md` layout, `plan/README.md` status.

**Tests:** `pytest hub/tests`: 57 pass.

**Not done / for the user's test**
- No real iPhone or headset was available. The runbook's step 4 fps check and the whole of section 5
  are the first real-hardware run. Unverified there:
  - Safari at 120 Hz, including from the Home Screen;
  - real decoding accuracy and false motion at margin 0.08.
- Glass-to-glass video latency wasn't measured: there's no camera. Relay is ~4 ms; FPV
  readback+encode ~100–150 ms.
