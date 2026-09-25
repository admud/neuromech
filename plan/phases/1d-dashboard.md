# Phase 1D: operator dashboard

**Agent:** opus, after 1C · **Runs:** Phase 1, in parallel with 1A, 1B, 1E, 1F

## Goal
A laptop browser page for whoever runs the demo: see what the decoder sees,
arm and stop, drive by keyboard, tune the BCI live, check every link,
simulate gaze when there's no headset, and show the **3D virtual sim**
(built by 1E and 1F) while we test without the physical robot.

## Stack
Plain HTML + JS ES modules, WebSocket, `createImageBitmap`. The twin is
embedded as an `<iframe>` of `/twin/`: no three.js code here.

## Read first
- [../protocol.md](../protocol.md): `/ws/dashboard`, `/ws/video`, `config`, `state`, dashboard messages
- [../architecture.md](../architecture.md)
- [../README.md](../README.md#rules-for-every-agent): git rules

## You own
`web/dashboard/` (e.g. `index.html`, `dashboard.js`, `style.css`)

## Constraints
Plain HTML + ES modules, **no build step, no CDN or external requests**.
Served by the hub at `/dashboard/`. Desktop Chrome/Edge. Readable from a
couple of metres away (big state indicators).

## Build

1. **Safety header** (always visible)
   - Big ARMED (green) / DISARMED (red) with `disarm_reason`.
   - ARM button → `{"type": "arm", "armed": true}`.
   - STOP button → `{"type": "arm", "armed": false}`.
   - **Esc anywhere, and Space when not typing in a field, = STOP.**

2. **Decoder panel**
   - Four score bars labelled with direction and frequency; winner highlighted.
   - Dwell progress (`dwell.count / dwell.needed`).
   - Active `command` (direction, `vx`/`vy`, `source`), `decode_ms`, `warnings`.

3. **Keyboard drive override**
   - Arrow keys / WASD while held → `{"type": "override", "direction": ...}`
     every 200 ms; `null` on release. Also an on-screen D-pad for the mouse.
   - Note that it only works while armed. Drop the override on window blur.

4. **Tuning form**
   - Fields: 4 frequencies, `window_s`, `margin`, `dwell`, `speed`,
     prefilled from `state.params` and `config`.
   - Apply → `set_config` with only the changed fields.
   - Show whether the change took (the next `state.params` / `config`).

5. **Links panel**
   - EEG: device, port, fs, channels, ok, `stalled_s`, per-channel `quality` if present.
   - Phone: connected, fps (red below 100), p95, dropped, rtt.
   - Robot: connected, name, rtt, telemetry, `watchdog_stopped`.
   - Video: `in_fps`, viewers.

6. **Video preview** from `/ws/video` (`createImageBitmap`, newest frame
   only, close replaced bitmaps).

7. **Sim gaze** (only when `state.sim` is not null): buttons up / down /
   left / right / none (keys 1–4, 0) → `sim_gaze`. Highlight the current gaze.

8. **Phone URL**: show `state.hub.phone_url` large, for typing into the
   iPhone.

9. **Virtual sim panel**, a large panel.
   - `<iframe src="/twin/?embed=1">` while the **Virtual robot** switch is
     ON (default ON, remembered in `localStorage`). The iframe itself is then
     the robot.
   - Switch OFF (real robot or `robot_sim` connected) → remove the iframe
     and show the video preview in its place.
   - A "full screen" button calls `requestFullscreen()` on the iframe.
     Don't open `/twin/` in a second tab while the embedded one is on: two
     virtual robots would keep replacing each other on `/ws/robot`.
   - The iframe must stay visible (hidden tabs are throttled and the
     virtual robot would freeze), so don't put it in a collapsed tab.
   - **Keys:** when the iframe has focus, key presses go to it, not to you.
     The twin forwards Esc, Space, arrows, WASD, 1–4 and 0 as
     `postMessage({type: "twin-key", event, key})`. Handle those exactly like
     your own key events. **STOP must work whichever frame has focus.**

10. **Connection**: auto-reconnect every 1 s with a DISCONNECTED banner;
   `ping` every 2 s.

11. **Demo mode `?demo=1`**: fake `config`/`state` so the page can be built
    before the hub exists. Then test against sol's `python -m hub --stub`.

## Acceptance
- [x] Every `state` field in protocol.md that matters to an operator is visible
- [x] STOP works via button, Esc, and Space (outside inputs), including while the twin iframe has focus
- [x] Override sends every 200 ms while held and `null` on release/blur
- [x] `set_config` sends only changed fields; UI reflects the hub's accepted values
- [x] Sim gaze controls appear only in sim mode
- [x] Sim iframe embedded; the Virtual robot switch adds/removes it; full-screen button works
- [x] Works in `?demo=1` and against `python -m hub --stub`
- [x] Handoff notes filled in, committed, @main tagged

## Handoff notes

**What exists** (`web/dashboard/`):
- `index.html`, `style.css`, and `dashboard.js` (all the logic).
- `demo.js`: a fake hub for `?demo=1` that behaves like the stub engine.
  It records every message it receives in `__dash.hub.log`, for tests.
- Reuses `../phone/net.js` (reconnecting WS), `../phone/video.js` (newest-frame
  video) and `../phone/demo.js` (test pattern). opus owns both directories.
- Safety header:
  - big ARMED/DISARMED with the disarm reason in words;
  - ARM (disabled while armed or with no hub) and a large STOP;
  - the current command (arrow, vx/vy, source);
  - the phone URL in large type;
  - hub dot + RTT, and a DISCONNECTED banner.
- Panels:
  - decoder: score bars labelled with frequency, winner highlighted, dwell
    pips, decode_ms, warnings;
  - drive: D-pad, current override, "not armed" note;
  - sim gaze: only when `state.sim` is set;
  - tuning;
  - links: EEG with per-channel quality, phone fps in red below 100, robot
    with telemetry, pose, collision and WATCHDOG STOP, video;
  - video preview.
- **Key handling:** holds are tracked per source (`k:` local keys, `t:` keys
  from the twin, `pad` D-pad), and the newest hold wins.
  - Twin holds expire 800 ms after their last keydown. Key-repeat refreshes
    them, so a keyup lost when the iframe loses focus can't leave the robot
    driving.
  - Window blur releases local and pad holds.
  - Buttons blur themselves after a click, so Space/Enter can never re-press ARM.
- Tuning:
  - Fields the user has edited turn yellow ("dirty") and aren't overwritten
    by incoming state.
  - Apply sends only the fields that differ from the hub's values.
  - The status reads "applied: ..." once the next `config`/`state` matches,
    or "not accepted: X (hub keeps Y)" after 1.5 s.
- The Virtual robot switch (default ON) is stored in `localStorage`
  (`neuromech.virtualRobot`).
  - OFF removes the iframe and moves the video canvas into the big panel.
  - ON puts the iframe back and the video returns to the small side panel.

**Tested** (Chrome over CDP with real key and mouse input):
- `?demo=1`:
  - ARM click arms; Esc and Space STOP; Space inside a number field doesn't.
  - ArrowUp held 1.1 s: overrides at 0, 70, 267, 468 ... 1067 ms, then
    `null` at release.
  - Blur sends `null`.
  - A forwarded twin arrow with no keyup expires: `null` at ~900 ms.
  - Tuning: margin + up freq sent as `{"margin":0.08,"freqs":{"up":12.5}}`,
    shown as applied. 50 Hz is rejected ("hub keeps 14") and the field
    reverts.
  - Key 1 sets the gaze.
  - The virtual switch removes/restores the iframe and remembers the setting.
- `python -m hub --stub` with the real `/twin/?embed=1` iframe:
  - it connects as robot `virtual`;
  - ArrowUp pressed *inside the iframe* drives it (override up, robot x
    advancing);
  - Space and Esc inside the iframe STOP it;
  - the STOP button works;
  - the full-screen button makes the iframe `document.fullscreenElement`.
- `python -m hub --device synthetic` (opus3's engine): `sim` is null, so the
  gaze panel is hidden. EEG quality rows render.

**Known limits:**
- While the iframe is full screen, Esc is taken by the browser to exit full
  screen and never reaches the page. Space still STOPs from full screen.
- Phone rtt shows "–" until `hub/server.py` copies the phone's
  `frame_stats.rtt_ms` into `state.phone.rtt_ms` (sol).
