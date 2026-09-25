# Phase 1A: hub server

**Agent:** sol · **Runs:** Phase 1, in parallel with 1B–1E

## Goal
The PC hub process: serves the phone, dashboard and twin pages, runs the four
WebSockets, broadcasts `state`, sends robot `cmd`s, and relays video. It
delegates every BCI and safety decision to `BciEngine` (Phase 1B). Also a
small headless robot simulator for testing the robot side of your own
protocol (and later the template for the RPi).

## Stack
Python 3.10, FastAPI + uvicorn, asyncio WebSockets. Robot sim: `websockets`
client + OpenCV.

## Read first
- [../protocol.md](../protocol.md): every route and message you implement
- [../architecture.md](../architecture.md)
- [../README.md](../README.md#rules-for-every-agent): git and environment rules

## You own
`hub/__init__.py`, `hub/__main__.py`, `hub/server.py`, `hub/video.py`,
`hub/netinfo.py`, `hub/stub_engine.py`, `hub/requirements.txt`,
`hub/sim/__init__.py`, `hub/sim/robot_sim.py`,
`hub/tests/__init__.py`, `hub/tests/test_server.py`, `hub/tests/test_robot_sim.py`

## Build

1. **Dependencies.** Install into the shared venv and record them:
   `control/.venv/Scripts/python.exe -m pip install fastapi uvicorn`, then list
   them in `hub/requirements.txt`. The venv already has `websockets` 16 and
   `httpx`. If uvicorn's websockets backend errors with websockets 16, add
   `wsproto` and run uvicorn with `ws="wsproto"`.

2. **`hub/__main__.py`**: `python -m hub [options]` from the repo root.
   - Options: `--device {cyton,synthetic,sim}` (default `cyton`), `--port`
     (COM port, default auto-detect), `--freqs 11,14,17,20`
     (up,down,left,right), `--window 3.0`, `--margin 0.06`, `--dwell 2`,
     `--speed 0.3`, `--model`, `--mode`, `--http-port 8765`, `--host 0.0.0.0`,
     and `--stub` (use `StubEngine`, see 5).
   - Build `EngineSettings` → `BciEngine` → `engine.start()` (blocking, a few
     seconds), then run uvicorn. Import `hub.bci` lazily so `--stub` works
     before 1B lands.
   - If `engine.start()` raises (e.g. no dongle found), print the message and
     exit non-zero, no traceback wall.
   - At startup print the phone and dashboard URLs for every LAN IPv4
     address, plus: *"If the phone can't connect, allow Python through
     Windows Firewall on Public networks."*
   - Ctrl+C → `engine.stop()` and a clean exit.

3. **`hub/server.py`**: `create_app(engine) -> FastAPI`. The engine is
   injected so tests can pass a stub.
   - Static: `web/phone/` at `/phone/`, `web/dashboard/` at `/dashboard/`
     and `web/twin/` at `/twin/` (`html=True`; serve `.js` as
     `text/javascript` so ES modules load). Those folders may not exist yet while other tracks are
     building, so don't crash if they're missing. `/` redirects to `/phone/`.
     `/api/health` returns `{"ok": true}`.
   - `/ws/phone`: send `config` on connect. Track connected phones and call
     `engine.set_phone_connected(True/False)` when the count goes 0↔1.
     `hello` → store. `frame_stats` → store latest. `arm` → `engine.handle(msg, "phone")`.
     `ping` → `pong`.
   - `/ws/dashboard`: send `config` on connect. `arm`, `set_config`,
     `override`, `sim_gaze` → `engine.handle(msg, "dashboard")`. `ping` → `pong`.
   - When `engine.handle` returns `True`, broadcast `engine.config_message()`
     to every phone and dashboard.
   - **State broadcast, 10 Hz:** `{"type": "state", "t_hub": ..., **engine.status(), phone, robot, video, hub}`
     as in the protocol. `phone.rtt_ms` comes from its pings;
     `robot.rtt_ms` from hub `ping`/robot `pong`.
   - `/ws/robot`: one robot at a time; a new connection closes the old one.
     Call `engine.set_robot_connected(...)`. Text → `hello`/`telemetry`/`pong`.
     Binary → video relay. Send `cmd` at 10 Hz **always** (zero velocity
     included), built from `engine.command()` with an increasing `seq` and
     `ttl_ms: 500`. Send `ping` at 1 Hz.
   - A client that errors or disconnects mid-send is dropped. It must never
     stop the broadcast loop or the robot `cmd` loop. Bad JSON is ignored.

4. **`hub/video.py`**: newest-frame relay. The robot publishes JPEG bytes;
   each `/ws/video` viewer has its own sender task that waits for a frame
   newer than the last one it sent, then sends the **newest**. Frames are
   never queued. Track `in_fps` (1 s moving count) and `viewers`.

5. **`hub/stub_engine.py`**: `StubEngine` implementing the full `BciEngine`
   interface from protocol.md with fake data: the winner cycles
   up → right → down → left → none every 3 s with plausible scores, and it
   handles `arm` / `set_config` / `override` / `sim_gaze` and arming rules
   roughly like the real one. **Land this early.** 1C, 1D and 1E test their pages
   against `python -m hub --stub` before 1B is ready.

6. **`hub/netinfo.py`**: LAN IPv4 addresses, most likely one first (UDP
   "connect" trick to find the default-route interface), skipping `127.*`
   and `169.254.*`. This laptop has Docker/WSL virtual adapters, so list all
   of them rather than guessing just one.

7. **`hub/sim/robot_sim.py`**: headless robot client, the reference
   implementation of the robot side of `/ws/robot`.
   `python -m hub.sim.robot_sim [--hub ws://127.0.0.1:8765/ws/robot] [--video test|webcam] [--camera 0] [--fps 20]`
   - Uses the installed `websockets` 16 client
     (`websockets.asyncio.client.connect`). Reconnects with backoff.
   - `hello` with `name: "sim"`. Sends JPEG frames as binary, 640x480,
     quality ~70.
   - **`test` video:** a simple generated frame with a HUD showing `vx`/`vy`,
     `seq`, watchdog state and a **wall clock with milliseconds**, for
     reading off glass-to-glass latency. Keep it simple: the 3D twin (1E) is
     the pretty simulator. **`webcam` video:** camera frames with the same HUD.
   - Integrates pose (`x`, `y`) from `cmd`s at `max_speed` 0.5 m/s and sends
     `telemetry` at 10 Hz with pose. Replies `pong` to `ping`.
   - **Watchdog (mandatory):** no `cmd` within `ttl_ms` → stop and report
     `watchdog_stopped: true`.
   - Isolate `get_frame()` and `drive(vx, vy)`: the RPi port (Phase 3A) only
     swaps those two.

8. **Tests**
   - `hub/tests/test_server.py` (pytest, FastAPI `TestClient`, a stub
     engine): health route; phone gets `config` first; phone `arm` reaches
     `engine.handle`; config rebroadcast when `handle` returns True; robot
     gets `cmd` messages with increasing `seq`; binary frame from robot
     reaches a `/ws/video` viewer; second robot connection replaces the first.
   - `hub/tests/test_robot_sim.py`: against a throwaway `websockets.serve`
     server, check `hello`, frames and telemetry arrive, `cmd` moves the pose
     the right way (`vy` positive = left), and the watchdog stops it.

## Acceptance
- [ ] `python -m hub --stub` serves `/api/health`, and `/phone/`, `/dashboard/`, `/twin/` once those folders exist
- [ ] `robot_sim` drives against `python -m hub --stub`; its watchdog works
- [ ] Phone and dashboard sockets receive `config` then `state` at ~10 Hz
- [ ] A robot client receives `cmd` at 10 Hz and its JPEGs reach `/ws/video` viewers with no queue build-up (slow viewer = skipped frames, not delay)
- [ ] Killing a client mid-stream never stops the broadcast or `cmd` loops
- [ ] `python -m hub --device synthetic` works once 1B has landed
- [ ] `control/.venv/Scripts/python.exe -m pytest hub/tests/test_server.py hub/tests/test_robot_sim.py` passes
- [ ] Handoff notes filled in, committed, @main tagged

## Handoff notes
_(fill in when done: what exists, how to run it, known gaps)_
