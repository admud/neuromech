# hub: the laptop hub

`python -m hub` is the centre of NeuroMech. It:
- reads EEG from the Cyton;
- decodes which flicker circle you're looking at;
- decides, with the safety rules, what the robot should do;
- talks to the operator display, the dashboard and the robot over
  WebSockets on one port (8765).

```
Cyton ──► bci/ (EEG + decoder + arbiter) ──► server.py ──► /ws/robot ──► robot (rover bridge, virtual robot, robot_sim)
                                                  │  ▲
            operator display (hub.gui) ◄── /ws/phone + /ws/video
            dashboard (browser)        ◄── /ws/dashboard + /ws/video
```

## Run

From the repo root, with the venv's Python:
```
control\.venv\Scripts\python -m hub --window 2                    # real headset (dongle auto-detected)
control\.venv\Scripts\python -m hub --window 2 --virtual-robot    # + the CPU-rendered virtual robot
control\.venv\Scripts\python -m hub --device sim                  # no headset: fake EEG
control\.venv\Scripts\python -m hub --stub                        # fake engine, for UI work only
```
At startup it prints the phone and dashboard URLs for every network adapter.

**Options** (all can also be changed live from the dashboard's Tuning and
Control panels):
- `--device cyton|synthetic|sim`: default `cyton`.
  - `synthetic` is brainflow's test board. It's a pure sine per channel
    and always decodes "right", so it's only for testing the plumbing.
  - `sim` is our fake EEG, which responds to simulated gaze and clenches.
- `--port COMx`: the dongle's port. Default: auto-detect the OpenBCI (FTDI)
  dongle. Bluetooth COM ports are never picked.
- `--freqs 11,14,17,20`: flicker frequencies for up, down, left, right.
- `--window 3.0`: decode window in seconds. **2** is what we recommend.
- `--margin 0.08`: how far the winner must beat the runner-up.
- `--dwell 2`: consecutive wins needed before a direction activates.
- `--speed 0.3`: normalised speed sent to the robot. The rover's speed is
  fixed on the Pi.
- `--model FILE --mode trca_cca`: an optional trained decoder from
  `control/ssvep_calibrate.py`. On our data it was worse than plain CCA.
- `--control hold|latch`, `--clench-threshold 8`, `--latch-max 3`: jaw-clench
  latch mode (see [`bci/`](bci/README.md)).
- `--virtual-robot`: also start `hub.sim.virtual` as a child process. It
  stops with the hub.
- `--http-port 8765`, `--host 0.0.0.0`.

## What's in here

- `__main__.py`: CLI; starts the engine, then the server.
- `server.py`: FastAPI app. It:
  - serves `web/` pages;
  - runs the four WebSockets;
  - broadcasts `state` 10 times a second;
  - sends robot `cmd`s 10 times a second;
  - checks liveness (a display or robot silent for 3 s counts as gone).
- `video.py`: newest-frame JPEG relay. It never queues, and never sends a
  frame older than 1 s.
- `netinfo.py`: LAN addresses for the printed URLs.
- `stub_engine.py`: a fake engine (`--stub`) for working on the pages.
- [`bci/`](bci/README.md): EEG board, decoder wiring, arbiter (hold/latch,
  safety), and the jaw-clench detector and recorder.
- [`gui/`](gui/README.md): the operator display (`python -m hub.gui`).
- [`ugv/`](ugv/README.md): the rover bridge (`python -m hub.ugv`).
- [`sim/`](sim/README.md): fake EEG, a headless robot, and the virtual robot.
- `tests/`: pytest suite (134 tests).

## Connections

These are the full message formats; the contract is
[`plan/protocol.md`](../plan/protocol.md).
- `/ws/phone`: the operator display (or the phone page). Receives `config`
  and `state`, and sends `arm`, `frame_stats` and `ping`. When the last
  display disconnects, the hub disarms with `phone_lost`.
- `/ws/dashboard`: the dashboard. It can also send `set_config`,
  `override` (keyboard drive), `sim_gaze` and `sim_clench`.
- `/ws/video`: JPEG frames from the robot to viewers.
- `/ws/robot`: one robot at a time; a new one replaces the old. Receives
  `cmd` (`vx`, `vy`, `ttl_ms`) 10 times a second, and sends
  `hello`, `telemetry` and JPEG frames.

## Safety rules

- **Starting state:** the hub starts **disarmed**, and the robot moves
  only while armed.
- **Arming** is always explicit: hold Enter in the display, or ARM on the
  dashboard.
- **Automatic disarm:**
  - the display is lost or goes quiet (`phone_lost`);
  - the robot link is lost (`robot_lost`);
  - EEG stops for more than 1.5 s, or the hub itself stalls (`eeg_stall`).
- **Commands never stop flowing:** `cmd` goes out 10 times a second even
  when the command is zero.
- **Every robot stops itself** if `cmd`s stop for `ttl_ms` (500 ms).

## Tests

```
control\.venv\Scripts\python -m pytest hub/tests
```
