# Phase 4: desktop operator GUI (Python, no browser)

**Agent:** opus · **Tests:** @main · **Status:** done 2026-09-26 (`dd675cc`), accepted by @main

**User decisions (2026-09-26):**
- Display: the laptop's built-in **120 Hz** panel. The external monitor is 30 Hz and unusable for flicker.
- Keep the **web dashboard** for tuning and status (without the 3D sim it's light).
- Test video: `hub.sim.robot_sim --video test` until the rover exists.
- Left/right stay **strafe**.
**Why:** Chrome on this laptop shares the Intel GPU between the flicker and
everything else and couldn't hold 120 fps (54–80 fps with late frames), and
the demo won't use the phone. The operator display becomes a native Python
window. The phone page (`web/phone/`) stays in the repo and keeps working.

## Goal
A full-screen, first-person operator display on the laptop:
- the robot's live camera feed filling the screen;
- four SSVEP circles overlaid on it (top = forward, bottom = back,
  left, right), flickering at their configured frequencies with exact,
  vsync-locked timing;
- arm / STOP / keyboard drive from the keyboard, and the key status on screen.

## Design

**A separate process that speaks the phone's protocol.** The GUI is just
another hub client: it connects to `/ws/phone` (config, state, arm,
frame_stats, ping) and `/ws/video` (JPEG frames), exactly like the phone
page. So the hub, the decoder, the safety rules and the robot link don't
change. Keeping it a separate process also means the decoder and web server
never compete with the render loop for Python's GIL, which would cause late
frames.

**Stack**
- **psychopy**, already installed. It's the same library `ssvep_bci.py` and
  `ssvep_calibrate.py` use, which the user has already run with the
  headset. It gives vsync'd flips, the predicted time of the next flip
  (`win.getFutureFlipTime`) and frame-interval recording.
- **OpenCV** (`cv2.imdecode`) for JPEG decoding, in a background thread.
- The **`websockets`** client, running in an asyncio loop on its own thread.

**Flicker**
- Brightness per circle: `L = 0.5 * (1 + sin(2π f t))`. `t` is the
  **predicted flip time** of the frame being drawn, not a frame counter.
  That keeps design rule 1, and a dropped frame can't shift the phase.
- Frequencies come from the hub's `config`, including live changes.
- Circles are opaque, each with a thin dark ring so the moving video around
  it doesn't bleed into its flicker. Diameter defaults to 16% of the short
  side (`--size`).
- Every frame's flip time and levels can be logged (`--log-frames`) so the
  real frequencies can be checked offline.

**Video**
- A receiver thread keeps only the newest JPEG, and a decoder thread turns
  it into RGB. The render loop uploads it to a texture only when a new frame
  has arrived (about 20 times a second), never inside a flicker frame's
  critical path.
- Letterboxed full screen; the circles sit on top.
- `--no-video` runs flicker only, for timing tests.

**On-screen status** (static, never flickering)
- ARMED / DISARMED and the reason.
- The winning target's ring.
- An arrow for the current command.
- A status line: fps, p95 frame interval, dropped frames, hub / EEG / robot
  link.
- A DISCONNECTED banner when the hub link is down.

**Keys**
- **Space or Esc: STOP** (disarm).
- **Hold Enter for 1 s: ARM.**
- **Arrows / WASD:** keyboard drive while armed. Sent through a second,
  dashboard-type connection, because the hub only accepts `override` from
  dashboard clients.
- **Q:** quit. It sends STOP first.
- **F:** toggle the timing overlay.

**Safety** (same as the phone)
- The hub counts the GUI as the phone: closing it, or 3 s of silence,
  disarms with `phone_lost`.
- Minimising the window sends STOP.
- The flicker keeps running while the hub is disconnected, as on the phone.

**GPU:** the window renders through OpenGL on whatever GPU Windows gives
python.exe. If it can't hold 120 fps on the Intel chip, set
`control\.venv\Scripts\python.exe` (and the base Python it launches) to
High performance in Windows Graphics settings.

## Files
`hub/gui/`, run as `python -m hub.gui`:
- `__main__.py`: CLI
  (`--hub 127.0.0.1:8765 --screen 0 --windowed --size 0.16 --no-video --log-frames FILE`);
- `app.py`: window, render loop, keys;
- `net.py`: the hub links;
- `video.py`: receive and decode;
- `hud.py`: status overlays;
- `hub/tests/test_gui_*.py`: logic tests that don't need a window (layout,
  flicker math, key/arm logic, net messages against a fake hub).

No hub changes are needed. An optional `hello.client = "desktop"` lets the
dashboard show which display is connected.

## Acceptance (@main runs these himself)
- [ ] Against `hub --device sim` + `robot_sim --video test`: config, state,
      ARM, STOP, keyboard drive and live frequency changes all work;
      sim gaze moves the robot the right way.
- [ ] On the laptop's 120 Hz panel with 20 fps video: about 120 fps, and
      at most 1% of frames late.
- [ ] Frequencies logged from real flips measure 11/14/17/20 Hz.
- [ ] Closing the GUI while armed → `phone_lost`; hub restart → reconnects;
      minimise → STOP.
- [ ] The phone page still works unchanged.

## Not in this phase
- The rover's Pi code (3A).
- Turning instead of strafing.
- Calibrating with this same display (a later step, so training matches
  the live stimulus).
