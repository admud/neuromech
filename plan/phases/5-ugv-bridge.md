# Phase 5: drive the real UGV from the hub

**Agent:** sol · **Tests:** @main · **Status:** plan, waiting for the user's answers and go

## What exists
The user's `ugv_controller.py` (currently in `C:\Users\User\Downloads`) is a
manual keyboard tool. It sends plain-text UDP packets to the Pi at
`NeuroMech.local:5005`: `FWD`, `BACK`, `LEFT`, `RIGHT`, `STOP`, one packet
per key press, and `STOP` on quit. So the Pi already runs a UDP listener
that drives the motors. The hub has no way to use it yet.

## Where things go
- **`robot/ugv_controller.py`:** the user's manual tool, copied in
  unchanged. It stays useful for driving the rover by hand and as a
  fallback.
- **`hub/ugv/` (`python -m hub.ugv`):** a new **UGV bridge** that runs on
  the laptop next to the hub.
  - It connects to the hub's `/ws/robot` exactly like the 3D sim and
    `robot_sim` do, with `hello.name: "ugv"`.
  - It turns the hub's `cmd` messages into the Pi's UDP commands.
  - **The Pi code doesn't change,** and neither do the hub, the decoder,
    the GUI or `protocol.md`.

## How the bridge works
- **Mapping** (the hub sends one direction at a time):
  - `vx > 0` → `FWD`
  - `vx < 0` → `BACK`
  - `vy > 0` → `LEFT`
  - `vy < 0` → `RIGHT`
  - zero → `STOP`
- **Resend every 100 ms,** following the hub's 10 Hz `cmd`, not only on
  change. UDP can drop packets, and repeating means a lost `STOP` is
  corrected within 0.1 s. If the Pi keeps the last command until the next
  one, the repeats are harmless.
- **The robot protocol, towards the hub:** `hello`, `telemetry` about 5
  times a second (the last command sent and whether the bridge's watchdog
  has stopped the rover), and replies to `ping`. That keeps the hub's 3 s
  liveness check happy. There's no pose, because the Pi doesn't report one.
- **Host:** `--host NeuroMech.local` (the default), or the Pi's IP if the
  `.local` name doesn't resolve on Windows; plus `--port 5005`. It resolves
  the name once at startup and prints the address.
- **Video:** the Pi's camera isn't covered by this controller. If the Pi
  serves a stream (for example MJPEG over HTTP), the bridge can pull it and
  forward the frames to the hub (`--video-url`), and the desktop GUI then
  shows the live camera. `--video test` gives a placeholder image meanwhile.

## Safety
1. **The hub already sends zero velocity** whenever it's disarmed, and on
   any lost link (phone/GUI, EEG, robot). That becomes `STOP`.
2. **Bridge watchdog:** no `cmd` from the hub for 500 ms (hub frozen or
   crashed) → send `STOP` three times, then keep sending `STOP`.
3. **Bridge exit** (Ctrl+C, a crash, the window closing) → send `STOP`
   three times before quitting. The hub also sees `robot_lost` and disarms.
4. **The Pi side is the gap.** If the Pi keeps driving on its last command
   until it hears `STOP`, then a laptop crash or a WiFi drop leaves the
   rover driving. **Strongly recommended:** add a timeout on the Pi (no
   packet for about 0.5 s → stop the motors). The bridge's 100 ms repeats
   then act as a heartbeat. It's a few lines in the Pi's listener; we can
   write it if we get that file.
5. **First run with the wheels off the ground.**

## Tests (@main)
- **Fake Pi:** a UDP listener on the laptop (`--host 127.0.0.1`) that
  records every packet. Check:
  - the mapping for each direction;
  - the 10 Hz resends;
  - `STOP` on disarm, look-away, Space/Esc;
  - `STOP` within 0.5 s when the hub is killed or frozen;
  - `STOP` when the bridge exits;
  - `robot_lost` in the hub.
- **Full loop:** `hub --device sim` plus the bridge plus the desktop GUI.
  Sim gaze produces the right UDP commands.
- **Then the real rover, run by the user:** wheels up, then on the floor at
  low speed.

## Open questions (need the user's answers)
1. **Pi behaviour:** does a command keep the rover moving until `STOP`
   (latched), or does it move briefly per packet? Is there any timeout on
   the Pi?
2. **LEFT/RIGHT on the Pi:** strafe or turn? The hub means strafe.
3. **Camera:** does the Pi stream video today? If so, what's the URL,
   port and format?
4. **Speed:** fixed on the Pi, or can it be set?
5. **Pi code:** can someone change it, e.g. to add the timeout? Where is it?
