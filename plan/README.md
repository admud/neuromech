# NeuroMech teleop build plan

Goal for the demo on **2026-09-26**: drive a robot from an iPhone showing
live video and four SSVEP targets, with the Cyton headset on the operator.
Until the physical robot is ready, the robot is a **3D virtual robot**
(digital twin) whose camera feed goes to the phone.

- [architecture.md](architecture.md): what we're building and why
- [protocol.md](protocol.md): **the contract** between tracks (routes,
  messages, Python interfaces, world file). Read it before writing code.
- [phases/](phases/): one brief per agent

## Phases

| Phase | Track | Agent | Stack | Builds | Owns |
|---|---|---|---|---|---|
| 1 | [1A hub server](phases/1a-hub-server.md) | **sol** | Python, FastAPI, uvicorn, asyncio WS; OpenCV | server, 4 WebSockets, video relay, CLI, stub engine, headless robot sim | `hub/__init__.py`, `hub/__main__.py`, `hub/server.py`, `hub/video.py`, `hub/netinfo.py`, `hub/stub_engine.py`, `hub/requirements.txt`, `hub/sim/__init__.py`, `hub/sim/robot_sim.py`, `hub/tests/__init__.py`, `hub/tests/test_server.py`, `hub/tests/test_robot_sim.py` |
| 1 | [1B BCI engine](phases/1b-bci-engine.md) | **opus3** | Python, numpy/scipy, brainflow/eegnb, pyserial, `ssvep_bci.Decoder` | dongle auto-detect, decoder wiring, arbiter + safety, SSVEP board simulator | `hub/bci/`, `hub/sim/sim_board.py`, `hub/tests/test_arbiter.py`, `hub/tests/test_engine.py`, `hub/tests/test_sim_board.py` |
| 1 | [1C phone page](phases/1c-phone-client.md) | **opus** | HTML/JS modules, Canvas/WebGL, WebSocket; iOS Safari | time-based flicker at 120 Hz, video, STOP/ARM, frame stats | `web/phone/` |
| 1 | [1D dashboard](phases/1d-dashboard.md) | **opus2** | HTML/JS modules, WebSocket; twin via iframe | operator dashboard with the twin embedded | `web/dashboard/` |
| 1 | [1E digital twin](phases/1e-digital-twin.md) | **fable** | three.js (vendored), WebGL, JS modules, WebSocket | 3D arena, virtual robot + physics, FPV camera → video feed, brain-control HUD | `web/twin/` |
| 2 | [2 integration](phases/2-integration.md) | **opus2** | everything | end-to-end in simulation, fixes, runbook, docs | anything |
| 3 | [3A RPi robot](phases/3a-rpi-robot.md) | sol | Python on Pi, picamera2, motor driver | real robot on `/ws/robot` | `robot/` |
| 3 | [3B AR twin](phases/3b-ar-twin.md) | fable | three.js, OpenCV (calibration, ArUco) | virtual walls overlaid on the real camera feed, geofence | `web/twin/`, `hub/tools/` |

Phase 1 is five parallel tracks. Phase 2 starts when all five are done.
Phase 3 is after the demo pipeline works and the robot exists, and is only
outlined for now. astra isn't assigned: nothing here is worth its cost and
latency. It's kept in reserve for a hard, narrow problem.

## How the pieces link

```
                          ┌─────────────── PC hub (1A sol) ───────────────┐
 Cyton ──USB dongle──►    │  BciEngine (1B opus3)  ◄── Python interface ──┤ server
                          │  board · Decoder · arbiter · SimSSVEPBoard    │
                          └──┬─────────────┬──────────────┬────────────┬──┘
                    /ws/phone│  /ws/video   │ /ws/dashboard│   /ws/robot│
                             │  (JPEG)      │ (state)      │ cmd ↓ JPEG+pose ↑
                             ▼              ▼              ▼            ▼
                     phone page (1C)   dashboard (1D) ──iframe──► twin (1E)
                     flicker + video    scores, arm,      mode=robot: IS the robot
                                        tuning, override  mode=view: follows the robot
                                                                 ▲
                              other robots on /ws/robot: robot_sim (1A) · RPi (3A)
```

| Link | Between | Contract |
|---|---|---|
| `BciEngine` Python API | 1A ↔ 1B | protocol.md → Python interfaces. 1A runs `--stub` until 1B lands. |
| `/ws/phone` + `/ws/video` | 1A ↔ 1C | `config`, `state`, `arm`, `frame_stats`, `ping`; JPEG frames |
| `/ws/dashboard` + `/ws/video` | 1A ↔ 1D | `state`, `config`, `arm`, `set_config`, `override`, `sim_gaze` |
| `/ws/robot` | 1A ↔ 1E (and robot_sim, RPi) | `cmd` at 10 Hz in; JPEG frames + pose telemetry out; watchdog |
| `/ws/dashboard` read-only | 1A → 1E | `state` for the 3D HUD |
| iframe + `postMessage` | 1D ↔ 1E | `/twin/?embed=1&mode=robot\|view`; twin forwards STOP keys |
| world file | 1E → 3B, hub | `web/twin/worlds/default.json` |

Every Phase 1 track can be built and tested on its own: 1A with a stub
engine, 1B with the SSVEP simulator, 1C/1D in `?demo=1` then against
`python -m hub --stub`, 1E against the stub hub.

## Rules for every agent

**Environment**
- Windows. Use the venv interpreter `control/.venv/Scripts/python.exe`
  (Python 3.10). Never the system `python` (3.14).
- Only **1A (sol)** installs Python packages (`fastapi`, `uvicorn` into
  `control/.venv`, recorded in `hub/requirements.txt`). Others use what's
  installed (numpy, scipy, brainflow, websockets, opencv-python). 1E vendors
  three.js with npm into `web/twin/vendor/`.
- Run hub code from the repo root: `control/.venv/Scripts/python.exe -m hub ...`

**Git: one shared working tree, branch `feat/teleop`**
- Touch only the files your track owns (table above). Need something outside
  them? Ask @main.
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

## Status

| Track | State |
|---|---|
| 0 plan + contract | done (@main) |
| 1A hub server | not started |
| 1B BCI engine | not started |
| 1C phone page | not started |
| 1D dashboard | not started |
| 1E digital twin | not started |
| 2 integration | blocked on 1A–1E |
| 3A RPi robot | later: needs the robot |
| 3B AR twin | later: needs the robot camera |

(@main updates this table. Agents report in their own brief's handoff notes.)

## Later, beyond Phase 3
- Rotation (two more targets or a mode switch).
- Calibration on the phone (needs phone↔PC clock sync for phase-aligned
  trials), session recording and replay.
