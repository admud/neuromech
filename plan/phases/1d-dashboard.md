# Phase 1D: operator dashboard

**Agent:** opus2 · **Runs:** Phase 1, in parallel with 1A–1C, 1E

## Goal
A laptop browser page for whoever runs the demo: see what the decoder sees,
arm and stop, drive by keyboard, tune the BCI live, check every link,
simulate gaze when there's no headset, and show the **3D digital twin**
(built by 1E) as the centrepiece.

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

9. **Digital twin panel**, the biggest panel, since this is the screen
   people will look at.
   - `<iframe src="/twin/?embed=1&mode=robot">` while the **Virtual robot**
     switch is ON (default ON, remembered in `localStorage`). The iframe
     itself is then the robot.
   - Switch OFF (a real or Python robot is connected) → `?embed=1&mode=view`.
   - A "full-screen twin" link opens `/twin/?mode=view` in a new tab.
     Never `mode=robot`: two virtual robots would keep replacing each other
     on `/ws/robot`.
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
- [ ] Every `state` field in protocol.md that matters to an operator is visible
- [ ] STOP works via button, Esc, and Space (outside inputs), including while the twin iframe has focus
- [ ] Override sends every 200 ms while held and `null` on release/blur
- [ ] `set_config` sends only changed fields; UI reflects the hub's accepted values
- [ ] Sim gaze controls appear only in sim mode
- [ ] Twin iframe embedded; the Virtual robot switch flips it between `mode=robot` and `mode=view`
- [ ] Works in `?demo=1` and against `python -m hub --stub`
- [ ] Handoff notes filled in, committed, @main tagged

## Handoff notes
_(fill in when done)_
