# NeuroMech teleop build plan

Goal for the demo on **2026-09-26**: drive the robot (simulated until the
RPi is ready) from an iPhone showing live video and four SSVEP targets, with
the Cyton headset on the operator.

- [architecture.md](architecture.md): what we're building and why
- [protocol.md](protocol.md): **the contract** between tracks (messages,
  routes, Python interfaces). Read it before writing code.
- [phases/](phases/): one brief per agent

## Phases

Two phases. Phase 1 runs as five parallel tracks, each owned by one agent
and touching only its own files. Phase 2 starts when all five are done.

| Phase | Track | Agent | Builds | Owns |
|---|---|---|---|---|
| 1 | [1A hub server](phases/1a-hub-server.md) | **sol** | FastAPI app, WebSockets, video relay, CLI, stub engine | `hub/__init__.py`, `hub/__main__.py`, `hub/server.py`, `hub/video.py`, `hub/netinfo.py`, `hub/stub_engine.py`, `hub/requirements.txt`, `hub/tests/__init__.py`, `hub/tests/test_server.py` |
| 1 | [1B BCI engine](phases/1b-bci-engine.md) | **opus** | board setup + dongle auto-detect, decoder wiring, arbiter, safety | `hub/bci/`, `hub/tests/test_arbiter.py`, `hub/tests/test_engine.py` |
| 1 | [1C phone page](phases/1c-phone-client.md) | **fable** | time-based flicker at 120 Hz, video, STOP/ARM, frame stats | `web/phone/` |
| 1 | [1D dashboard](phases/1d-dashboard.md) | **opus2** | operator dashboard | `web/dashboard/` |
| 1 | [1E simulators](phases/1e-simulators.md) | **opus3** | SSVEP board simulator, robot simulator client | `hub/sim/`, `hub/tests/test_sim_board.py`, `hub/tests/test_robot_sim.py` |
| 2 | [2 integration](phases/2-integration.md) | **astra** | end-to-end wiring, fixes, runbook, docs | anything |

```
Phase 1:  sol ─┐
          opus ├─┐
          fable ─┤
          opus2 ─┤
          opus3 ─┘
Phase 2:          └─► astra ──► user hardware test (headset + iPhone)
```

Dependencies inside Phase 1 go only through [protocol.md](protocol.md):
1A imports 1B's `BciEngine`, 1B imports 1E's `SimSSVEPBoard`. Both imports
happen at runtime, so each track can be built and tested on its own with
stubs.

## Rules for every agent

**Environment**
- Windows. Use the venv interpreter `control/.venv/Scripts/python.exe`
  (Python 3.10). Never the system `python` (3.14).
- Only **1A (sol)** installs packages (`fastapi`, `uvicorn` into
  `control/.venv`, recorded in `hub/requirements.txt`). Others use what's
  already installed (numpy, scipy, brainflow, websockets, opencv-python).
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
| 1E simulators | not started |
| 2 integration | blocked on 1A–1E |

(@main updates this table. Agents report in their own brief's handoff notes.)

## Later

Not scheduled before the demo:
- **RPi robot agent** (`robot/`): port `hub/sim/robot_sim.py` to the Pi
  (camera via picamera2, real motor driver). The `/ws/robot` protocol and the
  watchdog rule in protocol.md already cover it.
- Rotation (two more targets or a mode switch).
- Calibration on the phone (needs phone↔PC clock sync for phase-aligned
  trials), session recording and replay.
