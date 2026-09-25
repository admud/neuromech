# Phase 1C: phone page

**Agent:** fable · **Runs:** Phase 1, in parallel with 1A, 1B, 1D, 1E

## Goal
The page the operator holds: live robot video in the middle, four SSVEP
flicker targets around it, each at its own frequency, with rock-steady timing
at the iPhone 17's 120 Hz. This is the stimulus the whole BCI depends on. If
the flicker timing is wrong, nothing downstream can fix it.

## Read first
- [../protocol.md](../protocol.md): `/ws/phone`, `/ws/video`, `config`, `state`, phone messages
- [../architecture.md](../architecture.md): decision 2 (time-based flicker), iPhone setup
- `control/ssvep_bci.py` lines ~312–316: the desktop flicker, for reference
  (frame-counter based, which is exactly what we must *not* do on the phone)
- [../README.md](../README.md#rules-for-every-agent): git rules

## You own
`web/phone/` (e.g. `index.html`, `phone.js`, `flicker.js`, `video.js`,
`style.css`, `manifest.json`)

## Constraints
- Plain HTML + ES modules, **no build step, no CDN or external requests**
  (venue WiFi may have no internet). Served by the hub at `/phone/`.
- Target: iPhone 17 Safari, landscape, handheld. Also must work in desktop
  Chrome/Edge for development.

## Build

1. **Flicker renderer**
   - Brightness per target: `L = 0.5 * (1 + sin(2π · f · t))`, where `t`
     is the **rAF timestamp** in seconds. Never a frame counter. Grey level
     `round(255 * L)`, full 0–255 range.
   - Frequencies come from the latest `config`. A new `config_id` takes
     effect on the next frame.
   - Redraw the targets every frame. No per-frame allocations (no GC jank):
     preallocate and reuse.
   - Keep the per-frame work tiny and separate from video, e.g. a flicker
     canvas on top of a video layer that only updates when a new frame
     arrives. Your choice of Canvas 2D or WebGL. Measure before choosing.

2. **Layout** (landscape)
   - Four bars: up = top edge, down = bottom, left = left edge, right =
     right edge. Leave the **corners empty** with a gap between bars, so no
     two targets touch.
   - Bar thickness default 18% of the short side, tunable with `?bar=0.2`.
   - Respect `env(safe-area-inset-*)`: the Dynamic Island sits on a long
     edge in landscape and must not cover a bar.
   - Video letterboxed in the centre region. Dark grey background.
   - Portrait → "rotate to landscape" screen.

3. **Video**: `/ws/video`, binary JPEG per message. Decode with
   `createImageBitmap(new Blob([buf], {type: "image/jpeg"}))`. Keep only
   the newest: if a decode is in flight, drop older frames, and `close()`
   replaced bitmaps. Video must never stall the flicker.

4. **Feedback** (static, non-flickering)
   - Coloured outline on the current `winner` target.
   - Arrow for the active `command.direction` over the video.
   - Small status line: hub, EEG, robot link, measured fps.
   - `disarm_reason` banner when disarmed.

5. **Arming, thumb-friendly**
   - A big **STOP** button, always visible in a corner: tap → `{"type":"arm","armed":false}`.
   - When disarmed: **HOLD TO ARM**. A 1 s long-press with a progress ring
     sends `{"type":"arm","armed":true}`.
   - Clear ARMED / DISARMED state on screen.

6. **Frame stats**: record every rAF interval. Every 1 s send
   `frame_stats` (`fps`, `p95_ms`, `dropped` = intervals > 1.5x median,
   `window_s`) and show fps on screen. If fps stays < 100 for 3 s after
   start, show a dismissible hint: *Settings → Apps → Safari → Advanced →
   Feature Flags → turn off "Prefer Page Rendering Updates near 60fps"*.

7. **Connection**
   - `/ws/phone` and `/ws/video` on `location.host`.
   - Send `hello` on connect and `ping` every 2 s (show rtt).
   - Auto-reconnect every 1 s with a visible DISCONNECTED banner. The
     flicker keeps running.

8. **iOS niceties**
   - "Tap to start" overlay (user gesture; request fullscreen where
     supported; iPhone doesn't support it).
   - Meta tags: `apple-mobile-web-app-capable`,
     `apple-mobile-web-app-status-bar-style: black-translucent`,
     `viewport-fit=cover`, `user-scalable=no`.
   - `manifest.json` with `display: fullscreen` and `orientation: landscape`,
     so "Add to Home Screen" hides Safari's bars.
   - No scroll, bounce, zoom or text selection (`touch-action: none`,
     `overscroll-behavior: none`).

9. **Demo mode `?demo=1`**: no hub. Default config (11/14/17/20 Hz), a
   fake `state` cycling the winner, and a generated test pattern instead of
   video. Use it until sol's `python -m hub --stub` is up, then test against
   that.

## Acceptance
- [ ] Flicker is time-based and each target runs at its configured frequency (verify: log L(t) for a target and check the period; change freqs live via `config`)
- [ ] Desktop Chrome at 60 Hz and at a high-refresh monitor if available: p95 frame interval within ~1.2x the refresh interval **while video streams at 20 fps**
- [ ] No bars clipped by safe areas; corners empty; portrait handled
- [ ] STOP tap and HOLD TO ARM long-press send the right messages
- [ ] Works in `?demo=1` and against `python -m hub --stub`
- [ ] Handoff notes filled in (including what you measured), committed, @main tagged

## Handoff notes
_(fill in when done)_
