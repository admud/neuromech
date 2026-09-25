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
| `GET /api/health` | HTTP | anyone | `{"ok": true}` |
| `WS /ws/phone` | JSON text | phone page | see [Phone](#phone--wsphone) |
| `WS /ws/dashboard` | JSON text | dashboard page | see [Dashboard](#dashboard--wsdashboard) |
| `WS /ws/video` | binary | phone page, dashboard page | one JPEG per message, hub → viewer only |
| `WS /ws/robot` | JSON text + binary | robot (sim now, RPi later) | see [Robot](#robot--wsrobot) |

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
 "params": {"window_s": 3.0, "margin": 0.06, "dwell": 2, "speed": 0.3},  // engine
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
| `set_config` | any subset of `{"freqs": {"up": 11, ...}, "window_s": 2.0, "margin": 0.05, "dwell": 3, "speed": 0.4}` | engine validates, applies, hub rebroadcasts `config` if freqs changed |
| `override` | `{"direction": "up"\|"down"\|"left"\|"right"\|null}` | keyboard drive. Resend every 200 ms while a key is held; expires 500 ms after the last message. Needs `armed`. Beats BCI. |
| `sim_gaze` | `{"target": "up"\|...\|null}` | only with `--device sim`: which target the simulated user looks at |
| `ping` | `{"t_client": ...}` | hub replies `pong` |

## Robot ⇄ hub (`/ws/robot`)

Only one robot at a time. A new connection replaces (closes) the old one.

Robot → hub:

| kind | body |
|---|---|
| text `hello` | `{"type": "hello", "client": "robot", "name": "sim", "video": {"w": 640, "h": 480, "fps": 20}}` |
| text `telemetry` | ~2 Hz: `{"type": "telemetry", "vx": 0.3, "vy": 0.0, "watchdog_stopped": false, "battery_v": null}` plus optional extras (sim adds `x`, `y`) |
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

## Safety model (enforced by the engine)

- The robot moves **only while `armed`**. The hub starts disarmed.
- `arm {"armed": false}` from the phone or dashboard disarms immediately.
- Auto-disarm (sets `disarm_reason`):
  - last phone disconnects → `phone_lost`
  - EEG newest sample unchanged for > 1.5 s → `eeg_stall`
  - robot disconnects → `robot_lost`
- Re-arming is always an explicit user action.
- While armed with no confident, dwelled winner and no override → `vx = vy = 0`.

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
    margin: float = 0.06
    dwell: int = 2                   # consecutive decodes before a direction activates
    speed: float = 0.3               # normalised, 0..1
    interval_s: float = 0.25         # decode period
    model_path: str | None = None    # optional ssvep_calibrate.py .npz
    mode: str = "trca_cca"           # scorer used with model_path
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

### `hub.sim.sim_board.SimSSVEPBoard` (owner: Phase 1E, consumer: Phase 1B)
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
