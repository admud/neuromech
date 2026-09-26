# NeuroMech teleop build plan

Goal for the demo on **2026-09-26**: drive a robot from an iPhone showing
live video and four SSVEP targets, with the Cyton headset on the operator.
Until the physical robot is ready, the robot is a **3D virtual robot** in the
laptop browser whose camera feed goes to the phone. The sim is for testing
only.

- [architecture.md](architecture.md): what we're building and why
- [protocol.md](protocol.md): **the contract** between tracks (routes,
  messages, Python interfaces, world file). Read it before writing code.
- [phases/](phases/): one brief per agent
- [runbook.md](runbook.md): demo-day procedure for the headset + iPhone test

## Phases

### Phase 1: six tracks, built in parallel

**1A Hub server** ([brief](phases/1a-hub-server.md)): **sol**
- Stack: Python, FastAPI + uvicorn, asyncio WebSockets, OpenCV.
- Builds:
  - the PC server: the four WebSockets, 10 Hz state broadcast and robot `cmd`s, and the video relay;
  - the CLI;
  - a stub engine, so the web pages can be tested early;
  - a headless robot sim that becomes the Pi template.
- Owns: `hub/__init__.py`, `hub/__main__.py`, `hub/server.py`,
  `hub/video.py`, `hub/netinfo.py`, `hub/stub_engine.py`,
  `hub/requirements.txt`, `hub/sim/__init__.py`, `hub/sim/robot_sim.py`,
  `hub/tests/__init__.py`, `hub/tests/test_server.py`, `hub/tests/test_robot_sim.py`.

**1B BCI engine** ([brief](phases/1b-bci-engine.md)): **opus3**
- Stack: Python, numpy/scipy, brainflow/eegnb, pyserial, the existing `ssvep_bci.Decoder`.
- Builds:
  - COM port auto-detect for the dongle;
  - decoder wiring;
  - the arbiter (dwell, look-away = stop, arm/STOP, auto-disarm);
  - the SSVEP board simulator (fake EEG).
- Owns: `hub/bci/`, `hub/sim/sim_board.py`, `hub/tests/test_arbiter.py`,
  `hub/tests/test_engine.py`, `hub/tests/test_sim_board.py`.

**1C Phone page** ([brief](phases/1c-phone-client.md)): **opus**
- Stack: HTML/JS modules, Canvas/WebGL, WebSocket; iOS Safari.
- Builds: time-based flicker at 120 Hz, video, STOP / hold-to-arm, fps reporting.
- Owns: `web/phone/`.

**1D Dashboard** ([brief](phases/1d-dashboard.md)): **opus**, after 1C
- Stack: HTML/JS modules, WebSocket; the 3D sim embedded as an iframe.
- Builds: decoder scores, arm/STOP, keyboard drive, live tuning, link
  health, sim-gaze buttons, the 3D sim panel.
- Owns: `web/dashboard/`.

**1E 3D virtual sim** ([brief](phases/1e-virtual-sim.md)): **opus2**
- Stack: three.js (vendored), WebGL, JS modules, WebSocket.
- Builds:
  - a virtual arena whose robot *is* the robot on `/ws/robot`;
  - collisions with walls;
  - the robot's first-person camera streamed as the video feed to the phone;
  - the brain-control state shown in 3D.
- Owns: `web/twin/` except the two 1F files.

**1F Robot 3D model** ([brief](phases/1f-robot-model.md)): **astra**
- Stack: three.js primitives, one JS module.
- Builds:
  - our mecanum robot in 3D, built from the photo in code (no modelling software);
  - mecanum wheel kinematics;
  - a preview page.
- Owns: `web/twin/robot_model.js`, `web/twin/model.html`.
- Why astra: it's expensive on input and slow, but this task is narrow
  with small input (one photo, one contract) and pure spatial reasoning.

### Phase 2: integration

**2 Integration** ([brief](phases/2-integration.md)): **opus3**, after 1B
- Starts when all Phase 1 tracks are done and @main's reviews are fixed.
- Runs 14 end-to-end scenarios in simulation, fixes what breaks, measures
  fps/latency, writes `plan/runbook.md` for the user's headset + iPhone
  test, brings the docs up to date.
- Owns: anything.

### Phase 3: later, when the physical robot is ready (outline only)

**3A RPi robot** ([brief](phases/3a-rpi-robot.md)): **sol**
- Stack: Python on the Pi Zero, picamera2, GPIO → dual L298N driver.
- Builds: the real robot on `/ws/robot`, replacing the 3D sim in the loop.
- Owns: `robot/`.

## How the pieces link

```
Cyton ─USB dongle─► BciEngine (1B) ◄─Python API─► hub server (1A)
                                        │/ws/phone  │/ws/video  │/ws/dashboard  │/ws/robot
                                        ▼           ▼           ▼               ▼
                                   phone (1C)   dashboard (1D) ─iframe─► 3D sim (1E) ◄─ robot model (1F)
                                                                         IS the robot
                              other robots on /ws/robot: robot_sim (1A) · RPi (3A)
```

- **1A ↔ 1B:** the `BciEngine` Python interface (protocol.md). 1A runs
  `--stub` until 1B lands.
- **1A ↔ 1C:** `/ws/phone` (`config`, `state`, `arm`, `frame_stats`,
  `ping`) and `/ws/video` (JPEG frames).
- **1A ↔ 1D:** `/ws/dashboard` (`state`, `config`, `arm`, `set_config`,
  `override`, `sim_gaze`) and `/ws/video`.
- **1A ↔ 1E:** `/ws/robot` (`cmd` at 10 Hz in; JPEG frames + telemetry out;
  watchdog), plus `/ws/dashboard` read-only for the 3D HUD.
- **1D ↔ 1E:** iframe `/twin/?embed=1`; the sim forwards STOP keys to the
  dashboard with `postMessage`.
- **1F → 1E:** `createRobotModel()` and `mecanumWheelSpeeds()` (contract
  in the 1F brief). 1E uses a placeholder until 1F lands.
  `mecanumWheelSpeeds` is also the reference for 3A's motor mixing.

Every Phase 1 track can be built and tested on its own:
- 1A with a stub engine;
- 1B with the SSVEP simulator;
- 1C and 1D in `?demo=1`, then against `python -m hub --stub`;
- 1E against the stub hub with a placeholder robot;
- 1F in its own preview page.

## Rules for every agent

**Environment**
- Windows. Use the venv interpreter `control/.venv/Scripts/python.exe`
  (Python 3.10). Never the system `python` (3.14).
- Only **1A (sol)** installs Python packages (`fastapi`, `uvicorn` into
  `control/.venv`, recorded in `hub/requirements.txt`). Others use what's
  installed (numpy, scipy, brainflow, websockets, opencv-python). 1E vendors
  three.js with npm into `web/twin/vendor/` (1F uses the same copy).
- Run hub code from the repo root: `control/.venv/Scripts/python.exe -m hub ...`

**Git: one shared working tree, branch `feat/teleop`**
- Touch only the files your track owns (listed above). Need something
  outside them? Ask @main.
- Commit only your own paths: `git add <your paths>` then
  `git commit -m "..." -- <your paths>`.
- Never `git add -A`, `git commit -a`, `git stash`, `git checkout <branch>`,
  `git reset`, `git rebase` or `git push`. Other agents are working in the
  same tree at the same time.
- Commit in small steps so others can see progress.

**Contract**
- [protocol.md](protocol.md) is fixed. Adding optional fields is fine;
  renaming or removing anything needs @main.
- `control/` is read-only for Phase 1. Import from it, don't edit it.

**Done means**
- Every acceptance box in your brief is ticked.
- You filled in the *Handoff notes* section at the bottom of your brief
  (what exists, how to run it, anything unfinished) and committed it.
- You tagged @main once in the channel with a two-line summary.

## Reviews

@main reviews **and tests** each track when it hands off: running it
through its real interface, calling its functions, or building mock
counterparts where the other side isn't ready, plus direct integration
tests between tracks as soon as both sides exist. Findings go to the owner,
and the track is done once they're fixed and re-tested. fable is only asked
for advice if @main hits a problem it can't solve. Focus by track:
- **1A:** send loops can't die on a bad client; video relay never queues; robot `cmd` always at 10 Hz.
- **1B:** every safety rule in protocol.md; thread safety; no `input()` path; each decode counted once.
- **1C:** flicker is time-based and exact per target; no per-frame allocation; video can't stall the flicker.
- **1D:** STOP works from every path, including the sim iframe; override expiry.
- **1E:** watchdog; FPV frames never queue; axis signs; Z-up consistency.
- **1F:** kinematics signs vs roller handedness; frame/units contract.

## Status

(@main updates this. Agents report in their own brief's handoff notes.)
- 0 plan + contract: done (@main)
- 1A hub server: done, tested by @main (live hub, 3 s liveness timeouts, no-dongle error)
- 1B BCI engine: done, tested by @main (47 tests, full-loop sim integration, margin sweep)
- 1C phone page: done, tested by @main (19/19 e2e checks + reconnect)
- 1D dashboard: done, tested by @main (Space/Esc STOP incl. inside the sim iframe, keyboard override, sim gaze)
- 1E 3D virtual sim: done, re-tested by @main (FPV 19-20 fps into the hub, 21 fps on the phone; frames upright, colours right)
- 1F robot model: done, tested by @main in Chrome (32 draws, 15,648 tris, wheel signs, roller axes)
- 2 integration: done in simulation (opus3), accepted by @main (57 tests, integration 19/20 with the known look-away noise, frozen-hub re-run): scenarios 1-14, fixes, `e2e/`, [runbook.md](runbook.md). Next: the user's headset + iPhone test
- 3A RPi robot: later, needs the robot
- 5 UGV bridge: done (sol, `97c648b`), tested by @main against a fake Pi on localhost: FWD on gaze-up with 0 s delay then every 0.50 s; triple STOP within 63 ms on look-away / disarm / release / replaced-exit; hub-freeze watchdog STOP in 0.25-0.33 s; hardened in `61754b1` (no motion after a watchdog stop until the hub reconnects and sends a zero command; re-verified in 3 live runs). Real rover not yet driven.
- 4 desktop operator GUI: done (opus), tested by @main: full screen on the 120 Hz panel 119.7 fps, 0.28% late frames; flicker measured exactly 11/14/17/20 Hz (and a live change to 12 Hz) from real flip times; every circle's pixel = its level (859 frames); arm/STOP/gaze/phone_lost work. The operator display for the demo; the phone page is kept.

## Later, beyond Phase 3
- Rotation (mecanum can do it; needs two more targets or a mode switch).
- Calibration on the phone (needs phone↔PC clock sync for phase-aligned
  trials), session recording and replay.
