# web: browser pages served by the hub

Plain HTML/JS with no build step and no CDN, so they work offline. When the
hub is running they're at `http://<laptop>:8765/...`.

## `dashboard/`: operator dashboard

`http://localhost:8765/dashboard/`, in any browser.
- **Safety header:** ARMED/DISARMED and the reason, ARM, and a large STOP
  (Esc/Space).
- **Decoder:** score bars per target, the winner, dwell progress, warnings.
- **Drive:** keyboard override (arrows/WASD) and an on-screen D-pad.
- **Tuning:** frequencies, window, margin, dwell and speed, applied live.
- **Control:** the hold/latch switch, a clench meter with a threshold
  slider, the maximum latch time, the latched state, and a "sim clench"
  button (sim only).
- **Links:** EEG (per-channel quality), display fps, robot telemetry,
  video rate.
- **Video preview.**
- **Virtual robot switch:** keep it **OFF** when using the Python virtual
  robot (`--virtual-robot`) or the rover. When ON, it embeds the browser 3D
  sim, which becomes the robot and takes over the slot.
- `?demo=1` runs the page with a fake hub.

## `twin/`: browser 3D sim (three.js)

`http://localhost:8765/twin/`. It connects as the robot `virtual`, drives
our mecanum robot through the arena, and streams its first-person view.
- `robot_model.js`: our robot built from shapes in code, including mecanum
  roller geometry and `mecanumWheelSpeeds()`. `model.html` previews it.
- `worlds/default.json`: the arena (walls, spawn point, robot camera). The
  Python virtual robot uses the same file.
- `vendor/three/`: vendored three.js (MIT).
- **Caveat:** it renders on the laptop's Intel GPU. With the Python
  display running at the same time, that display drops to about 85 fps.
  Prefer `python -m hub --virtual-robot`, which renders on the CPU.

## `phone/`: phone page (kept, not used for the demo)

`http://<laptop-ip>:8765/phone/`: the original iPhone operator page.
- Full-screen video with four flicker circles; clock-timed flicker at up
  to 120 Hz.
- STOP and hold-to-arm.
- Installable (Share → Add to Home Screen).

The demo uses the Python display (`python -m hub.gui`) instead, because a
browser on this laptop couldn't hold steady frame timing.
