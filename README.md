# NeuroMech

Drive a robot with your eyes. NeuroMech is our project for the
[Singapore Defense Tech Hackathon (SDTH) 2026](https://luma.com/sdth-2026).

The operator wears an **OpenBCI Cyton** EEG headset and watches a screen
showing the robot's view, surrounded by four circles that flicker at
different frequencies (up, down, left, right). Looking at a circle produces
an **SSVEP**, a brain response at that circle's frequency, over the visual
cortex. The laptop decodes which circle you're looking at and drives a
4-wheel **mecanum rover** forward, back, or sideways.

```
Cyton headset ──USB radio dongle──► laptop hub ──UDP──► rover (Raspberry Pi)
                                        │
                                        └──► operator display: robot view + 4 flicker circles
```

Two ways to drive:
- **Hold** (default): the rover moves while you keep looking at a circle,
  and stops about 2 s after you look away.
- **Latch:** look at a circle to *select* it, **clench your jaw** to go,
  and clench again to stop. It releases on its own after 3 s.

## What works today

- **Decoding:** training-free filter-bank CCA, reused from our SSVEP code in
  [`control/`](control/). On a clean recording it scored **94% at a 2 s
  window** (100% at 3 s).
- **Operator display:** a Python/psychopy window, not a browser. It runs
  at **120 fps** on the laptop panel with **exact** flicker frequencies,
  measured from the real frame times.
- **Rover link:** the hub's commands become the Pi's UDP
  `FWD/BACK/LEFT/RIGHT/STOP`, with its own safety watchdog.
- **Jaw-clench latch mode**, with a guided recorder to tune the threshold.
- **A virtual robot** for testing without the rover: a CPU-rendered 3D
  arena whose first-person view shows on the display.
- **Tests:** 134 automated tests, plus end-to-end scripts that run the
  whole loop in simulation.

Not done yet: the rover's camera stream (the display shows a placeholder
until the Pi streams video).

## Setup (Windows, Python 3.10)

```
cd control
py -3.10 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pip install -e .
.venv\Scripts\python -m pip install -r ..\hub\requirements.txt
```

Always use this venv's Python (`control\.venv\Scripts\python`). A newer
system Python can't run psychopy.

## Before you drive: headset check

1. **Unplug the laptop charger.** Mains noise swamps the EEG otherwise.
2. **Seat the ear clips** (reference and ground) and the four electrodes
   that matter: **O1, O2, P7, P8**.
3. **Check contact:** `control\.venv\Scripts\python control\contact_viz.py`.
   It finds the dongle's COM port itself.
   - Each channel should read a few µV, with only a small 50 Hz peak.
   - Press **A** for the alpha test: O1/O2 alpha should jump when you close
     your eyes.
4. **Close it** (Q) before starting the hub. Only one program can use the
   dongle at a time.

## Run

All commands are from the repo root. Start the hub, pick a robot, then
start the display.

**Virtual robot (no rover needed):**
```
control\.venv\Scripts\python -m hub --window 2 --virtual-robot
control\.venv\Scripts\python -m hub.gui
```

**Real rover** (laptop and Pi on the same network, e.g. the iPhone hotspot):
```
control\.venv\Scripts\python -m hub --window 2
control\.venv\Scripts\python -m hub.ugv --video none
control\.venv\Scripts\python -m hub.gui
```
The bridge looks up the rover at `NeuroMech.local`. Pass `--host <Pi IP>`
if that name doesn't resolve.

**Options:**
- **Latch mode:** add `--control latch` (and `--clench-threshold N`) to
  the hub command.
- **No headset:** add `--device sim` to the hub. You then drive with the
  dashboard's simulated-gaze and simulated-clench buttons.
- **Dashboard (optional):** `http://localhost:8765/dashboard/` in any
  browser. It shows decoder scores, link health, live tuning, and the
  hold/latch switch. Keep its **Virtual robot** switch **off**: that
  switch starts the browser 3D sim, which would take over the robot slot.

**Display keys:**
- **Hold Enter 1 s:** arm.
- **Space / Esc:** STOP.
- **Arrows / WASD:** drive by keyboard while armed.
- **F:** timing readout.
- **Q:** STOP and quit.

**Safety:** the rover moves only while armed. Any lost link (display, EEG,
robot) disarms. The rover bridge sends `STOP` on its own if the hub goes
quiet for 0.5 s.

## Repository layout

- [`control/`](control/README.md): SSVEP decoding. Our scripts on top of
  EEG-ExPy: decoder, calibration, evaluation, contact check.
- [`hub/`](hub/README.md): the laptop hub, `python -m hub`. EEG engine,
  safety logic, WebSockets, video relay.
  - [`hub/bci/`](hub/bci/README.md): board and dongle auto-detect,
    decoder wiring, hold/latch arbiter, jaw-clench detector and recorder.
  - [`hub/gui/`](hub/gui/README.md): the operator display (psychopy, 120 Hz).
  - [`hub/ugv/`](hub/ugv/README.md): bridge to the rover's UDP commands.
  - [`hub/sim/`](hub/sim/README.md): simulators. Fake EEG, a headless
    robot, and the CPU-rendered virtual robot.
- [`web/`](web/README.md): browser pages served by the hub. Dashboard,
  phone page (kept, not used for the demo), and the three.js 3D sim.
- [`robot/`](robot/README.md): the rover side. The team's manual UDP
  controller.
- [`e2e/`](e2e/README.md): end-to-end scenario scripts in simulation.
- [`plan/`](plan/README.md): design docs. Architecture, the
  [protocol](plan/protocol.md) between the parts, the phase briefs, and the
  [runbook](plan/runbook.md).
- [`CLAUDE.md`](CLAUDE.md): a guide for AI agents working in this repo.

## Tuning notes

- **Window:** `--window 2` is the sweet spot on our data. It responds in
  about 1.9 s, with fewer wrong moves than 3 s. The CLI default is still 3.
- **Frequencies:** keep 11/14/17/20 Hz. Another set (11/13/15/17.5)
  decoded much worse for our operator.
- **No trained model:** plain CCA beat the trained TRCA models on every
  recording.
- **Evaluate a recording** the way the hub drives:
  `control\.venv\Scripts\python control\ssvep_eval_live.py <calib.npz> --window 2`.

## Tests

```
control\.venv\Scripts\python -m pytest hub/tests
node e2e/integration.mjs      # needs a fresh hub --device sim on 127.0.0.1:18931
```

## Credits and licences

- [`control/`](control/) builds on [EEG-ExPy](https://github.com/NeuroTechX/EEG-ExPy)
  (BSD-3-Clause).
- The 3D sim uses [three.js](https://threejs.org), vendored under
  `web/twin/vendor/` (MIT).
