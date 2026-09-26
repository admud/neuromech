# CLAUDE.md

Guide for agents working in this repo. Keep it accurate: if you change what
it describes, update it in the same commit.

## What this is

**NeuroMech**, our project for the Singapore Defense Tech Hackathon (SDTH)
2026. Demo: **2026-09-26**.

An operator wearing an EEG headset drives a mecanum-wheel robot with their
eyes. They hold an iPhone showing the robot's live video, surrounded by four
flickering targets (up/down/left/right), each at its own frequency. Looking
at one produces an SSVEP at that frequency. The PC decodes it and sends the
robot a velocity command. Looking away from the targets stops the robot.

```
Robot camera ──WiFi──► PC hub ──WiFi──► iPhone Safari (video + 4 flicker targets)
Robot motors ◄──WiFi── PC hub ◄──USB radio dongle── OpenBCI Cyton headset
```

Until the physical robot exists, the robot is **virtual**: a three.js sim
in the laptop browser drives a model of our robot through a 3D arena and
streams its first-person camera to the phone as the video. It's for testing
only; once the real robot is in, its camera feed replaces the sim's.

## Status (2026-09-25)

- `control/`: **working**. SSVEP decoder tested with the real headset.
- `hub/`, `web/`: **working in simulation** (Phase 1 accepted, Phase 2
  integration done: scenarios 1–14 run end to end with `--device sim` and the
  virtual robot). Not yet run with the real headset + iPhone together: that
  test follows [plan/runbook.md](plan/runbook.md). Phases and status are in
  [plan/README.md](plan/README.md).
- `robot/` (RPi agent): Phase 3, after the robot exists.

## Repo map

```
CLAUDE.md               this file
README.md               short project readme
plan/                   build plan: start at plan/README.md
  architecture.md       system design, decisions log, latency budget, iPhone setup
  protocol.md           THE CONTRACT: routes, messages, Python interfaces, safety model
  phases/               one brief per agent (1a..1f parallel, 2 integration, 3a later)
  runbook.md            demo-day procedure for the headset + iPhone test; troubleshooting; measurements
  assets/               reference material (robot photo)
control/                SSVEP BCI (EEG-ExPy fork + our scripts). Has its own README.
  ssvep_bci.py          live decoder GUI; `Decoder` class (filter-bank CCA) is reused by the hub
  ssvep_trca.py         calibrated decoders (TRCA-CCA, TRCA)
  ssvep_calibrate.py    record calibration trials -> .npz
  ssvep_eval.py         offline decoder comparison / ITR
  contact_viz.py        live electrode-contact dashboard (alpha test); auto-detects the dongle
  occipital_check.py    terminal signal-quality check
  eegnb/                upstream EEG-ExPy package (device drivers etc.), installed editable
  examples/, doc/       upstream EEG-ExPy, not ours
  .venv/                Python 3.10 venv (gitignored); the one venv for the whole repo
hub/                    PC hub, Python package, run as `python -m hub`
  server.py             FastAPI app: pages + /ws/phone /ws/dashboard /ws/video /ws/robot
  video.py              newest-frame JPEG relay
  stub_engine.py        fake BciEngine for UI work (`--stub`)
  gui/                  desktop operator display (psychopy): full-screen video + 4 flicker circles; `python -m hub.gui`
  bci/                  board open + dongle auto-detect, decoder wiring, arbiter (safety)
  sim/                  sim_board.py (fake EEG with SSVEP), robot_sim.py (headless robot, RPi template)
  tests/                pytest
web/                    static pages served by the hub, no build step
  phone/                iPhone page: flicker targets + video + STOP/ARM (kept, not used for the demo)
  dashboard/            operator dashboard (embeds the twin in an iframe)
  twin/                 three.js 3D sim; the page IS the virtual robot on /ws/robot
    robot_model.js      our robot built from primitives + mecanumWheelSpeeds() (no modelling software)
    model.html          standalone preview of the robot model
    worlds/default.json the virtual arena (walls, spawn, robot camera)
    vendor/three/       vendored three.js (no CDN)
e2e/                    browser/sim end-to-end scenario scripts (node + headless Chrome over CDP); see e2e/README.md
robot/                  [Phase 3] Raspberry Pi robot agent
```

## Environment

- **Windows 11.** Git Bash and PowerShell both available.
- **Python: always the venv**, `control/.venv/Scripts/python.exe` (3.10).
  The system `python` is 3.14 and can't run psychopy/psychxr. To recreate the venv:
  ```
  cd control
  py -3.10 -m venv .venv
  .venv\Scripts\python -m pip install -r requirements.txt
  .venv\Scripts\python -m pip install -e .
  ```
  The hub's extra deps are in `hub/requirements.txt` (installed into the same venv).
- The web pages are plain HTML/JS with no build step and **no CDN** (venue
  WiFi may be offline). Node is used only to run `e2e/` scripts.

## Run

```
# existing BCI tools (from control/)
.venv\Scripts\python ssvep_bci.py --port COM8          # desktop flicker GUI + live decode
.venv\Scripts\python ssvep_bci.py --device synthetic   # no headset
.venv\Scripts\python contact_viz.py                    # electrode contact (dongle auto-detected)

# hub (from repo root)
control\.venv\Scripts\python -m hub                    # real headset, dongle auto-detected
control\.venv\Scripts\python -m hub --device sim       # fake EEG; drive via dashboard "sim gaze"
control\.venv\Scripts\python -m hub --stub             # fake engine, for UI work
control\.venv\Scripts\python -m hub.gui                # operator display, full screen on the 120 Hz laptop panel
control\.venv\Scripts\python -m hub.gui --windowed --duration 30 --log-frames f.csv   # timing check
control\.venv\Scripts\python -m hub.gui.analyze f.csv   # fps, late frames, measured flicker frequencies
control\.venv\Scripts\python -m hub.sim.robot_sim --video test   # headless fake robot
#   phone:     http://<laptop-lan-ip>:8765/phone/
#   dashboard: http://localhost:8765/dashboard/   (its sim iframe is the virtual robot)

# tests
control\.venv\Scripts\python -m pytest hub/tests
node e2e/integration.mjs                               # needs a fresh `hub --device sim --http-port 18931 --host 127.0.0.1`
cd control && .venv\Scripts\python -m pytest tests     # upstream tests
```

## Hardware facts

- **OpenBCI Cyton**, 8 ch, 250 Hz, channel order Fp1 Fp2 C3 C4 P7 P8 O1 O2
  (brainflow rows 1–8). Decoding uses **O1, O2, P7, P8**.
- The Cyton talks to its **USB dongle over OpenBCI's radio, not Bluetooth**.
  The dongle is an FTDI serial port whose COM number varies (COM6, COM8, ...).
  This laptop also has Bluetooth serial ports (COM3, COM4); those are never the headset.
- **iPhone 17**, 120 Hz. Safari needs *Feature Flags → "Prefer Page Rendering
  Updates near 60fps"* **off** to exceed 60 fps. Handheld, landscape.
- **Robot:** 4 mecanum wheels, two-deck aluminium chassis, Raspberry Pi Zero,
  dual L298N-style motor driver, LM2596 buck, AA packs, camera not fitted yet
  ([photo](plan/assets/robot-photo-1.jpg)). Forward/back/strafe only, no rotation yet.
  Wheel mixing: `mecanumWheelSpeeds` in `web/twin/robot_model.js`.

## Design rules that must not be broken

1. **Flicker is time-based:** brightness = `0.5*(1+sin(2π f t))` from the frame
   timestamp. Never derive it from a frame counter on the phone: refresh rate varies.
2. **Decoders must be phase-invariant** (`cca`, `trca_cca`). Phone flicker
   isn't phase-locked to the EEG, so full `trca` is unusable live.
3. **Reuse `control/ssvep_bci.Decoder`; don't fork it.** `import ssvep_bci`
   must not load psychopy (it's imported only inside `main()`); keep it that way.
4. **Never call eegnb's `EEG(device="cyton", serial_port=None)`**: it prompts
   with `input()` and hangs a server. Auto-detect the port first.
5. **Safety:** the robot moves only while armed; the hub starts disarmed;
   any link loss disarms; re-arming is explicit; `cmd` goes out at 10 Hz even
   when zero; every robot implementation stops itself if `cmd`s stop for `ttl_ms`.
6. **Video relay never queues:** newest frame wins, stale frames are dropped.
7. **One robot protocol:** the 3D sim (`virtual`), `robot_sim` (`sim`) and
   the RPi (`rpi`) all speak `/ws/robot` identically. Only one is connected
   at a time; a new one replaces the old. Never open `/twin/` twice.
8. **[plan/protocol.md](plan/protocol.md) is the contract.** Change it
   deliberately and update every side.

## Conventions

- Python style follows `control/ssvep_*.py`: plain modules, argparse CLIs,
  numpy/scipy, docstrings and comments that explain *why*.
- Velocities are normalised `[-1, 1]`, ROS axes: `vx` forward+, `vy` left+.
- Target ids and order: `up, down, left, right`. Default freqs 11/14/17/20 Hz.
- World frame: metres, x forward, y left, z up, heading = yaw CCW from +x.
- `control/` is upstream-derived. Change it only when the task needs it,
  and keep `setup.py` reading `EEG-ExPy_README.rst` (not `README.rst`).
- **Git:** work on a feature branch (currently `feat/teleop`), never commit
  to `main` directly. In multi-agent phases several agents share one working
  tree, so commit only your own paths (`git commit -- <paths>`) and never
  stash, reset, rebase, switch branches or push.

## Gotchas

- Venue WiFi often isolates clients (phone can't reach the laptop). Fallback:
  iPhone Personal Hotspot with the laptop and Pi joined to it.
- Windows Firewall must allow Python on **Public** networks for the phone to connect.
- This laptop has Docker/WSL virtual adapters, so the "LAN IP" guess can be
  wrong. The hub prints all candidates.
- Browsers throttle hidden tabs: the 3D sim in a background tab freezes
  (and its FPV feed stops). Keep it visible.
- Keys pressed inside the sim iframe don't reach the dashboard; the sim
  forwards STOP keys with `postMessage` (see protocol.md).
- `brainflow` warns about `pkg_resources` at import; harmless (setuptools is pinned `<81`).
- The Cyton's USB dongle must be in GPIO6 mode (switch on the dongle) to stream.
- `--device synthetic` is brainflow's test board: a pure sine at 5 Hz x channel
  number (C4 = 20 Hz), so it decodes "right" all the time. Use `--device sim`
  to test behaviour.
- In a full-screen sim iframe, Esc only exits full screen; Space still STOPs.
- The laptop's Chrome renders on the Intel GPU (4K panel at 1.5x). The phone page on the
  laptop drops to ~60 fps with uneven frames while the dashboard's 3D sim runs, which garbles
  the flicker. Set Chrome to the RTX 3080 (Windows Graphics settings → High performance).
- The decoder margin defaults to 0.08: at 0.06 the robot crept ~10% of the time
  while looking away in sim. Live look-away-to-stop is ~2.4 s (3 s window).
