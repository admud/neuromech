# Protocol and interface contract

This file is the contract between the Phase 1 tracks. They are built at the
same time by different agents, so **nobody changes a message, field or
signature here without telling @main first**. Additive optional fields are
fine; renames and removals are not.

## Network

One hub process on the PC serves everything on one port.

| Setting | Value |
|---|---|
| Host | `0.0.0.0` (all interfaces) |
| Port | `8765` (`--http-port` to change) |
| Transport | HTTP for pages, WebSocket for everything live |
| Auth | none (LAN only, hackathon) |

### Routes

| Route | Kind | Who connects | Payload |
|---|---|---|---|
| `GET /` | HTTP | anyone | redirect to `/phone/` |
| `GET /phone/` | static | iPhone Safari | `web/phone/` |
| `GET /dashboard/` | static | laptop browser | `web/dashboard/` |
| `GET /twin/` | static | laptop browser, or iframe in the dashboard | `web/twin/` (3D virtual sim, the virtual robot) |
| `GET /api/health` | HTTP | anyone | `{"ok": true}` |
| `WS /ws/phone` | JSON text | phone page | see [Phone](#phone--wsphone) |
| `WS /ws/dashboard` | JSON text | dashboard page; desktop display (`hub.gui`); twin page and [read-only viewers](#read-only-viewers-external-sites) (never send) | see [Dashboard](#dashboard--wsdashboard) |
| `WS /ws/video` | binary | phone page, dashboard page, desktop display, read-only viewers | one JPEG per message, hub → viewer only |
| `WS /ws/robot` | JSON text + binary | the robot: twin page in `mode=robot`, `hub.sim.robot_sim`, or the RPi | see [Robot](#robot--wsrobot) |

## Conventions

- Every text message is a JSON object with a `"type"` string.
- Unknown `type`s and unknown fields are ignored, never an error.
- Times are seconds as floats. `t_hub` is the hub's `time.monotonic()`;
  `t_client` is whatever clock the client uses (echoed back untouched).
- Target ids are always `"up"`, `"down"`, `"left"`, `"right"`, in that order.
- Velocities are **normalised** to `[-1, 1]` (fraction of the robot's max
  speed). Axes follow ROS REP-103: `vx` forward positive, `vy` **left**
  positive.

| Direction | `vx` | `vy` |
|---|---|---|
| up | `+speed` | 0 |
| down | `-speed` | 0 |
| left | 0 | `+speed` |
| right | 0 | `-speed` |
| none | 0 | 0 |

## Hub → phone and dashboard

### `config`
Sent on connect and whenever the target set changes.
```json
{"type": "config", "config_id": 3,
 "targets": [{"id": "up", "freq": 11.0}, {"id": "down", "freq": 14.0},
             {"id": "left", "freq": 17.0}, {"id": "right", "freq": 20.0}]}
```
`config_id` increments on every change. The phone must switch to the new
frequencies on the next frame.

### `state`
Sent 10 times a second to every phone and dashboard. Clients use the fields
they need and ignore the rest. Fields marked *engine* come from
`BciEngine.status()`; the rest are added by the server.

```json
{"type": "state", "t_hub": 1234.5,

 "armed": false,                       // engine
 "disarm_reason": "startup",           // engine: startup|user|phone_lost|eeg_stall|robot_lost|null
 "winner": "up",                       // engine: decoder winner this decode, or null
 "scores": {"up": 0.31, "down": 0.05, "left": 0.04, "right": 0.03},   // engine
 "command": {"vx": 0.3, "vy": 0.0, "direction": "up", "source": "bci"},  // engine; source bci|override|none
 "dwell": {"direction": "up", "count": 1, "needed": 2},  // engine
 "decode_ms": 11.8,                    // engine
 "params": {"window_s": 3.0, "margin": 0.08, "dwell": 2, "speed": 0.3},  // engine
 "eeg": {"device": "cyton", "port": "COM8", "fs": 250,
         "channels": ["P7", "P8", "O1", "O2"], "ok": true, "stalled_s": 0.0,
         "quality": [{"name": "O1", "std_uv": 5.2, "railed": false}]},     // engine; quality optional
 "sim": {"gaze": "up"},                // engine; null unless device == "sim"
 "warnings": ["11 and 22 Hz share a harmonic"],   // engine

 "phone": {"connected": true, "fps": 119.7, "p95_ms": 9.0, "dropped": 0, "rtt_ms": 14},
 "robot": {"connected": true, "name": "sim", "rtt_ms": 7,
           "telemetry": {"vx": 0.3, "vy": 0.0, "watchdog_stopped": false}},
 "video": {"in_fps": 19.6, "viewers": 2},
 "hub": {"phone_url": "http://192.168.1.23:8765/phone/",
         "dashboard_url": "http://192.168.1.23:8765/dashboard/"}}
```
(`//` comments are documentation only; real messages are plain JSON.)

### Phase 6 `state` fields (optional, engine)
Jaw-clench latch. Clients that don't know them ignore them.
```json
{"control_mode": "latch",                 // "hold" (gaze drives) | "latch" (gaze selects, clench toggles)
 "latched": "up",                         // latched direction, or null
 "latched_at": 1233.9,                    // hub monotonic time the latch started, or null
 "latch": {"elapsed_s": 1.2, "max_s": 3.0, "left_s": 1.8},   // null unless latched
 "clench": {"z": 2.1,                     // peak combined EMG z over the last 0.2 s
            "threshold": 8.0, "count": 4,
            "fired_at": 1234.1,           // hub monotonic time of the last clench, or null
            "ignored_at": 1230.2,         // last clench with no target to latch, or null
            "last": {"t": 1234.1, "result": "latched", "direction": "up"},
            "channels": ["Fp1", "Fp2", "P7", "P8"]},
 "params": {"control_mode": "latch", "clench_threshold": 8.0, "latch_max_s": 3.0, "...": "..."}}
```
- `clench.last.result`: `latched`, `unlatched`, `no_target` (no dwelled
  winner in the 0.5 s before the clench), `not_armed`, `hold_mode` (detected
  but hold mode ignores clenches). `last` is null until the first clench.
- While latched, `command.source` is `"bci"`.

### `pong`
Reply to `ping`: `{"type": "pong", "t_client": 17.2, "t_hub": 1234.5}`.

## Phone → hub (`/ws/phone`)

| type | when | body |
|---|---|---|
| `hello` | on connect | `{"client": "phone", "ua": "...", "screen": {"w": 2622, "h": 1206, "dpr": 3}}` |
| `frame_stats` | every 1 s | `{"fps": 119.7, "p95_ms": 9.0, "dropped": 0, "window_s": 1.0}` |
| `arm` | user action | `{"armed": true}` to arm (long-press), `{"armed": false}` to STOP (tap) |
| `ping` | every 2 s | `{"t_client": 17.2}` |

`dropped` = frames in the window whose interval was more than 1.5x the
median interval.

## Dashboard → hub (`/ws/dashboard`)

| type | body | effect |
|---|---|---|
| `arm` | `{"armed": bool}` | same as phone |
| `set_config` | any subset of `{"freqs": {"up": 11, ...}, "window_s": 2.0, "margin": 0.05, "dwell": 3, "speed": 0.4}`, plus (Phase 6) `control_mode` `"hold"`/`"latch"`, `clench_threshold` 1–500, `latch_max_s` 0.5–30 | engine validates, applies, hub rebroadcasts `config` if freqs changed |
| `override` | `{"direction": "up"\|"down"\|"left"\|"right"\|null}` | keyboard drive. Resend every 200 ms while a key is held; expires 500 ms after the last message. Needs `armed`. Beats BCI. |
| `sim_gaze` | `{"target": "up"\|...\|null}` | only with `--device sim`: which target the simulated user looks at |
| `sim_clench` | `{}` or `{"duration_s": 0.6}` | only with `--device sim`: inject a jaw-clench EMG burst (Phase 6) |
| `ping` | `{"t_client": ...}` | hub replies `pong` |

## Read-only viewers (external sites)

For something outside the repo that only shows the hub's data, like the demo
presentation site (2026-09-27): live video, the four decoder scores, and what's driving.
- **Hubs:** the real hub is `<laptop>:8765`, where `<laptop>` is the laptop's Tailscale name or its hotspot IP. For development, run
  a sim hub next to it:
  `python -m hub --device sim --window 2 --control latch --virtual-robot --http-port 8766`,
  then use `<laptop>:8766`. It doesn't touch the headset or the real hub.
- **Sockets:** `/ws/dashboard` for `config` + `state` (10 Hz), and `/ws/video` for JPEG frames.
  Open one of each for the whole site.
  - Plain `ws://`, so the viewer must be served over `http` (an `https` page can't open them).
  - The HTTP routes send no CORS headers: don't `fetch()` them.
  - Reconnect with backoff. Treat the hub as offline after 2.5 s with no `state`.
- **Never send on `/ws/dashboard`** (it takes operator commands), except `ping`.
  - Never connect to `/ws/phone` or `/ws/robot`.
  - Never load `/dashboard/`, `/twin/` or `/phone/` on the viewer machine. In a fresh browser the
    dashboard's Virtual robot switch is on, and its twin would replace the real rover on `/ws/robot`.
- **Scores:** `scores` are raw filter-bank CCA scores (weighted sum of squared canonical
  correlations over 3 bands, weights 1.25/0.67/0.50).
  - Theoretical range 0–2.42; in practice ~0.03–0.7, and all 0.0 before the first decode.
  - They're updated every 0.25 s, so the 10 Hz `state` repeats values.
  - The top score counts as `winner` only if it beats the runner-up by `params.margin`.
- **Which is activating, weakest to strongest:**
  1. `winner` (null = no clear target);
  2. `dwell` (`count` of `needed` decodes in a row);
  3. `command.direction`: what the robot is told right now (null = stopped, always null while disarmed).
  - In latch mode, `latched` drives until a second clench, STOP or `latch.left_s` runs out.
  - A change of `clench.count` marks a clench; `clench.last.result` says what it did.
- **Video:** newest frame only.
  - 640×360 from the rover camera (the bridge scales it to 640 wide), 640×480 from the simulators.
  - The rate follows the robot. While the rover drives, the bridge repeats the last pre-drive frame
    (`robot.telemetry.video_frozen`).

## Robot ⇄ hub (`/ws/robot`)

Only one robot at a time. A new connection replaces the old one, which is
closed with code 4001, reason `"replaced"` (the 3D sim then stops
reconnecting; `robot_sim` and the RPi keep retrying).
Three implementations speak this, and the hub can't tell them apart except
by `hello.name`: the 3D sim's virtual robot (`"virtual"`), the headless
Python sim (`"sim"`), and later the Raspberry Pi (`"rpi"`).

Robot → hub:

| kind | body |
|---|---|
| text `hello` | `{"type": "hello", "client": "robot", "name": "virtual"\|"sim"\|"rpi", "video": {"w": 640, "h": 480, "fps": 20}}` |
| text `telemetry` | 2–20 Hz (10 Hz recommended): `{"type": "telemetry", "vx": 0.3, "vy": 0.0, "watchdog_stopped": false, "battery_v": null, "x": 1.2, "y": -0.4, "heading": 0.0, "collision": false}`. Pose fields are optional (the virtual robot and `robot_sim` send them): `x`, `y` in metres in the world frame, `heading` in radians. Optional `video_frozen: true` means the robot is re-sending a held frame instead of live video (the rover bridge does this while driving, because its camera browns out). The desktop display doesn't mark it, by the user's choice. |
| text `pong` | `{"type": "pong", "t_hub": 1234.5}` (echo of `ping`) |
| binary | one complete JPEG frame per message. Target 640x480, quality ~70, <= 20 fps |

Hub → robot:

| type | rate | body |
|---|---|---|
| `cmd` | 10 Hz, **always**, including zero velocity | `{"type": "cmd", "seq": 812, "vx": 0.3, "vy": 0.0, "ttl_ms": 500}` |
| `ping` | 1 Hz | `{"type": "ping", "t_hub": 1234.5}` |

**Robot watchdog (mandatory on every robot implementation):** if no `cmd`
arrives within `ttl_ms` of the last one, stop the motors and report
`watchdog_stopped: true`.

## World frame and world file

- Metres. x forward (from the spawn heading), y left, z up. `heading` is
  yaw, counter-clockwise from +x. Robot `cmd` velocities are in the
  **robot** frame. With no rotation, heading stays at the spawn heading.
- The virtual world lives in `web/twin/worlds/default.json` (owner: 1E),
  in this shape:

```json
{"name": "default",
 "arena": {"size": [6.0, 4.0]},
 "spawn": {"x": -2.5, "y": 0.0, "heading": 0.0},
 "robot": {"radius": 0.15, "max_speed_mps": 0.5,
           "camera": {"height_m": 0.25, "pitch_deg": -10, "hfov_deg": 70, "w": 640, "h": 480}},
 "walls": [{"x": 0.0, "y": 1.0, "w": 2.0, "d": 0.1, "h": 0.4, "yaw_deg": 0}]}
```
Box positions are their centres. `w` runs along the box's local
x, `d` along its local y. `robot.camera` is the source of truth for the FPV
camera. The robot's physical dimensions come from the 3D model's `dims`
(`web/twin/robot_model.js`, 1F); `robot.radius` is only a fallback.

## Browser-to-browser: sim iframe → dashboard

When the dashboard embeds the sim in an iframe, key presses inside the
iframe don't reach the dashboard. The sim forwards Esc, Space, arrows,
WASD, 1–4 and 0:
```js
window.parent.postMessage({type: "twin-key", event: "keydown" | "keyup", key: "Escape"}, "*")
```
The dashboard treats these exactly like its own key events (Esc/Space = STOP).

## Safety model (enforced by the engine)

- The robot moves **only while `armed`**. The hub starts disarmed.
- `arm {"armed": false}` from the phone or dashboard disarms immediately.
- Auto-disarm (sets `disarm_reason`):
  - last phone disconnects → `phone_lost`
  - EEG newest sample unchanged for > 1.5 s → `eeg_stall`
  - robot disconnects → `robot_lost`
- Re-arming is always an explicit user action.
- While armed with no confident, dwelled winner and no override → `vx = vy = 0`.
- Latch mode (Phase 6): gaze alone never moves the robot. A clench latches
  the dwelled winner from the 0.5 s before it; a clench while latched always
  stops. The latch also releases on STOP, any disarm or auto-disarm, a
  `control_mode` change, and after `latch_max_s` (default 3 s). Nothing
  latches while disarmed, and re-arming never restores a latch. The keyboard
  override beats the latch while held.

## Python interfaces

### `hub.bci.config.EngineSettings` (owner: Phase 1B)
```python
@dataclass
class EngineSettings:
    device: str = "cyton"            # "cyton" | "synthetic" | "sim"
    port: str | None = None          # None -> auto-detect the OpenBCI dongle
    freqs: dict[str, float] = field(default_factory=lambda: {
        "up": 11.0, "down": 14.0, "left": 17.0, "right": 20.0})
    window_s: float = 3.0
    margin: float = 0.08
    dwell: int = 2                   # consecutive decodes before a direction activates
    speed: float = 0.3               # normalised, 0..1
    interval_s: float = 0.25         # decode period
    model_path: str | None = None    # optional ssvep_calibrate.py .npz
    mode: str = "trca_cca"           # scorer used with model_path
    control_mode: str = "hold"       # Phase 6: "hold" | "latch"
    clench_threshold: float = 8.0    # robust z of the EMG envelope
    latch_max_s: float = 3.0
    clench_channels: list[str] = ["Fp1", "Fp2", "P7", "P8"]
```

### `hub.bci.engine.BciEngine` (owner: Phase 1B, consumer: Phase 1A)
All methods except `start`/`stop` are thread-safe and return in well under
1 ms, because the server calls them from the asyncio event loop.
```python
class BciEngine:
    def __init__(self, settings: EngineSettings) -> None: ...
    def start(self) -> None: ...      # blocking: open board, start stream, settle, start decoding
    def stop(self) -> None: ...       # stop decoding, release the board
    def config_message(self) -> dict: ...   # full `config` message incl. "type"
    def status(self) -> dict: ...           # the *engine* fields of `state`
    def handle(self, msg: dict, source: str) -> bool: ...
        # source: "phone" | "dashboard". Handles arm, set_config, override,
        # sim_gaze. Returns True if the target config changed (server then
        # rebroadcasts config_message()).
    def set_phone_connected(self, connected: bool) -> None: ...
    def set_robot_connected(self, connected: bool) -> None: ...
    def command(self) -> dict: ...    # {"vx", "vy", "direction", "source"}; polled at 10 Hz
```

### `hub.sim.sim_board.SimSSVEPBoard` (owner and consumer: Phase 1B)
Stands in for a brainflow `BoardShim` as far as `ssvep_bci.Decoder` cares.
```python
class SimSSVEPBoard:
    sfreq: int                     # 250, like the Cyton
    eeg_rows: list[int]            # [1..8]
    eeg_names: list[str]           # Cyton order: Fp1 Fp2 C3 C4 P7 P8 O1 O2
    def __init__(self, freqs: list[float], fs: int = 250, snr: float = 0.5, seed: int | None = None): ...
    def prepare_session(self) -> None: ...
    def start_stream(self) -> None: ...
    def stop_stream(self) -> None: ...
    def release_session(self) -> None: ...
    def get_current_board_data(self, n: int) -> np.ndarray: ...  # (n_rows, <=n), newest last, like brainflow
    def set_gaze(self, index: int | None) -> None: ...   # index into freqs, None = looking at the video
    def set_freqs(self, freqs: list[float]) -> None: ...
```
