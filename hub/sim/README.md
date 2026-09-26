# hub/sim: simulators

These let you test the whole loop without a headset, without the rover, or
without either.

## Fake EEG: `sim_board.py`

Used with `python -m hub --device sim`. `SimSSVEPBoard` generates realistic
8-channel EEG:
- background noise with a 1/f spectrum;
- 10 Hz alpha;
- 50 Hz mains.

The dashboard's controls change what it generates:
- **Sim gaze buttons** (or keys 1–4, 0) add an SSVEP at the chosen target's
  frequency, strongest on O1/O2.
- **Sim clench** (key K) injects a jaw-clench muscle burst, for testing
  latch mode.

## Virtual robot: `virtual.py`

A robot with no browser, and the one to use with the operator display:
```
control\.venv\Scripts\python -m hub --window 2 --virtual-robot    # the hub starts it for you
control\.venv\Scripts\python -m hub.sim.virtual [--hub ws://127.0.0.1:8765/ws/robot] [--world web/twin/worlds/default.json] [--fps 20] [--minimap]
```
- It loads the same arena as the browser 3D sim
  (`web/twin/worlds/default.json`).
- Movement uses mecanum kinematics, collides with the walls and slides
  along them.
- It stops itself if commands stop for 500 ms.
- It renders the robot's **first-person view on the CPU** with
  numpy/OpenCV (about 2 ms per frame) and streams it at 20 fps. It never
  touches the GPU, so the display keeps its 120 Hz.
- `--minimap` adds a small top-down map in the corner.
- When the hub starts it, it also exits with the hub. If another robot
  connects, it steps aside (close code 4001) instead of fighting for the
  slot.

## Headless robot: `robot_sim.py`

A simple robot client with no 3D world:
```
control\.venv\Scripts\python -m hub.sim.robot_sim [--hub ws://127.0.0.1:8765/ws/robot] [--video test|webcam] [--camera 0] [--fps 20]
```
- **Video:** a test image showing the current command and a millisecond
  clock, for latency checks, or the laptop webcam.
- **Movement:** it integrates its position and stops itself if commands
  stop.
- **It's the reference robot:** the rover bridge (`hub/ugv/`) reuses its
  test image, and a Pi agent would start from its `get_frame()` /
  `drive()` split.

**Only one robot at a time.** Run either the virtual robot, `robot_sim`,
or the rover bridge, never two together.
