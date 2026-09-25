# Phase 2: integration, end-to-end test, runbook

**Agent:** opus2 (after finishing 1D) · **Runs:** after 1A–1E have all handed off

## Goal
Turn five independently built pieces into one working system, prove the
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
   | 12 | Drive the virtual robot into a wall; through the gates | Stops and slides at walls, `collision` in telemetry; gates light and the lap timer runs |
   | 13 | Esc / Space while the twin iframe has focus | STOP still works |
   | 14 | Full-screen twin tab (`mode=view`) next to the dashboard | Follows the robot smoothly; no fight over `/ws/robot` |

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
- [ ] Scenarios 1–14 pass (or each exception is written up with a reason)
- [ ] Measurements recorded in the runbook
- [ ] `plan/runbook.md` lets the user run the hardware test without asking anyone
- [ ] `CLAUDE.md`, `README.md`, `plan/README.md` match the code
- [ ] All tests pass

## Handoff notes
_(fill in when done)_
