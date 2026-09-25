# Phase 1A: hub server

**Agent:** sol · **Runs:** Phase 1, in parallel with 1B–1E

## Goal
The PC hub process: serves the phone and dashboard pages, runs the four
WebSockets, broadcasts `state`, sends robot `cmd`s, and relays video. It
delegates every BCI and safety decision to `BciEngine` (Phase 1B).

## Read first
- [../protocol.md](../protocol.md): every route and message you implement
- [../architecture.md](../architecture.md)
- [../README.md](../README.md#rules-for-every-agent): git and environment rules

## You own
`hub/__init__.py`, `hub/__main__.py`, `hub/server.py`, `hub/video.py`,
`hub/netinfo.py`, `hub/stub_engine.py`, `hub/requirements.txt`,
`hub/tests/__init__.py`, `hub/tests/test_server.py`

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
   - Static: `web/phone/` at `/phone/` and `web/dashboard/` at `/dashboard/`
     (`html=True`). Those folders may not exist yet while other tracks are
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
   roughly like the real one. **Land this early.** 1C and 1D test their pages
   against `python -m hub --stub` before 1B is ready.

6. **`hub/netinfo.py`**: LAN IPv4 addresses, most likely one first (UDP
   "connect" trick to find the default-route interface), skipping `127.*`
   and `169.254.*`. This laptop has Docker/WSL virtual adapters, so list all
   of them rather than guessing just one.

7. **`hub/tests/test_server.py`** (pytest, FastAPI `TestClient`, a stub engine):
   health route; phone gets `config` first; phone `arm` reaches
   `engine.handle`; config rebroadcast when `handle` returns True; robot gets
   `cmd` messages with increasing `seq`; binary frame from robot reaches a
   `/ws/video` viewer; second robot connection replaces the first.

## Acceptance
- [ ] `python -m hub --stub` serves `/api/health`, and `/phone/` + `/dashboard/` once those folders exist
- [ ] Phone and dashboard sockets receive `config` then `state` at ~10 Hz
- [ ] A robot client receives `cmd` at 10 Hz and its JPEGs reach `/ws/video` viewers with no queue build-up (slow viewer = skipped frames, not delay)
- [ ] Killing a client mid-stream never stops the broadcast or `cmd` loops
- [ ] `python -m hub --device synthetic` works once 1B has landed
- [ ] `control/.venv/Scripts/python.exe -m pytest hub/tests/test_server.py` passes
- [ ] Handoff notes filled in, committed, @main tagged

## Handoff notes
_(fill in when done: what exists, how to run it, known gaps)_
