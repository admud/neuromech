# Architecture

NeuroMech lets an operator drive an omnidirectional robot with their eyes.
They hold an iPhone showing the robot's live camera feed surrounded by four
flickering targets. Looking at a target produces an SSVEP (steady-state
visually evoked potential) at that target's frequency, which the EEG headset
picks up, the PC decodes, and the robot turns into motion.

## The loop

```
 Robot camera ──WiFi /ws/robot──► PC hub ──WiFi /ws/video──► iPhone (Safari)
      ▲                             │  ▲                     live video + 4 flicker targets
      │ cmd 10 Hz                   │  │ arm / frame_stats          │
      │                             ▼  │                            │ operator looks at a target
 Robot motors ◄──── arbiter ◄── decoder ◄── EEG ◄──USB radio dongle── Cyton headset
```

Everything goes through the PC hub. The phone and the robot never talk to
each other.

## Hardware

| Part | Details |
|---|---|
| EEG | OpenBCI **Cyton**, 8 channels, 250 Hz. Talks to its **USB dongle** over OpenBCI's own radio (not Bluetooth); the dongle shows up as a COM port that changes between machines (COM6, COM8, ...). Decoding uses O1, O2, P7, P8. |
| PC | Windows laptop running the hub. Python 3.10 venv at `control/.venv`. |
| Phone | **iPhone 17**, 120 Hz ProMotion, **handheld** in landscape. Web page in Safari, no app. |
| Robot | **Omni-wheel** robot on a Raspberry Pi with a camera. Moves forward/back/strafe; no rotation for now. RPi code is out of scope until after the hub works (see [README](README.md#later)). |
| Network | Local WiFi. iPhone Personal Hotspot is the fallback if the WiFi blocks device-to-device traffic. |

## Components

### PC hub: `hub/` (Python, one process)
- **Server** (`hub/server.py`, FastAPI + uvicorn): static pages, the four
  WebSockets, 10 Hz `state` broadcast, 10 Hz robot `cmd` sender, video relay.
- **BCI engine** (`hub/bci/`): opens the board (Cyton, brainflow synthetic, or
  the SSVEP simulator), runs `ssvep_bci.Decoder` from `control/` unchanged,
  and feeds its output to the **arbiter**, which applies dwell, arming and
  auto-disarm rules and produces the velocity command.
- **Video relay** (`hub/video.py`): holds only the newest JPEG from the robot
  and sends each viewer the newest frame when it's ready for one. Stale frames
  are dropped, never queued, so latency can't build up.
- **Simulators** (`hub/sim/`): an SSVEP board that fakes a user looking at a
  chosen target, and a robot client that behaves exactly like the RPi will
  (and becomes the template for it).

### Phone page: `web/phone/`
Plain HTML/JS, no build step, served by the hub.
- Landscape, full screen. Video in the middle, four flicker bars on the
  edges: up = top, down = bottom, left = left, right = right.
- Selected target highlighted, current command shown, STOP / ARM control.
- Reports its real frame rate to the hub every second.

### Operator dashboard: `web/dashboard/`
Laptop browser page for whoever runs the demo: decoder scores, arm/STOP,
keyboard drive override, live tuning (frequencies, window, margin, dwell,
speed), link health (EEG, phone fps, robot, video), simulated gaze buttons.

## Key design decisions

1. **Reuse the decoder, don't rewrite it.** `control/ssvep_bci.py`'s
   `Decoder` (filter-bank CCA) is already tested with the real headset. The
   hub imports it; `import ssvep_bci` does not load psychopy (that only
   happens inside `main()`), so nothing in `control/` needs to change.
2. **Each target has its own frequency, and flicker is time-based.** The
   phone computes each target's brightness as
   `0.5 * (1 + sin(2π · f · t))` from the frame's timestamp, not from a frame
   counter. The desktop GUI uses a frame counter, which is only correct at a
   fixed, known refresh rate; phones change refresh rate on the fly. With
   time-based flicker the frequency is right at any refresh rate.
3. **Phase-invariant decoding only** (`cca`, or `trca_cca` with a model). The
   phone's flicker isn't phase-locked to the EEG, so full `trca` is out, as it
   already is in `ssvep_bci.py`.
4. **Look away = stop.** No confident winner means zero velocity. No 5th
   target.
5. **Robot never moves unless armed**, and loses its arming on any link
   failure. The robot has its own 500 ms watchdog on top of that.
6. **One port, WebSockets everywhere.** Simple to firewall, works from Safari
   over plain HTTP.

## Threads and timing

| Thread | Rate | Work |
|---|---|---|
| brainflow (native) | 250 Hz | fills the ring buffer |
| `Decoder` thread | every 0.25 s | FBCCA on the newest `window_s` of EEG (~10 ms) |
| engine loop | every 0.05 s | reads each new decode once, runs the arbiter, stall check |
| asyncio loop (uvicorn) | 10 Hz | `state` broadcast, robot `cmd`; relays video as it arrives |

## Latency budget

| Stage | Typical |
|---|---|
| Camera capture + JPEG encode (robot) | 30–60 ms |
| Robot → hub → phone (WiFi x2) | 10–40 ms |
| Phone decode + display | 10–20 ms |
| **Video total** | **~100–150 ms** |
| SSVEP decision (window fills with the new target, plus dwell) | **~1–2 s** |

The BCI decision dominates. Speed defaults to 0.3 of max; window, margin
and dwell can be tuned live from the dashboard.

## iPhone setup (needed for 120 Hz)

- Safari caps web animation at 60 fps by default. Turn **off**
  *Settings → Apps → Safari → Advanced → Feature Flags →
  "Prefer Page Rendering Updates near 60fps"*.
- Low Power Mode off, Auto-Lock Never, brightness max.
- The page shows its measured fps, so we can see whether we actually got
  120 Hz. Whether the flag also applies when launched from the Home Screen
  (which hides Safari's bars) is checked in Phase 2.

## Decisions log

| Question | Answer (user, 2026-09-25) |
|---|---|
| Robot | Raspberry Pi; its code comes later |
| "Variable framerate" | Each target flickers at its own frequency |
| iPhone | iPhone 17, assume no power saving; get it to full frame rate |
| Headset link | Cyton USB dongle, COM port varies |
| Phone use | Handheld |
| Driving | Omni: forward/back/strafe. No stop target: look away = stop |
| Rotation | Not now, start with 4 targets |
| Network | Local WiFi |
| Demo | 2026-09-26 |
| Testing | The decoder already works with the headset; no separate phone-SSVEP gate. Test everything together at the end. |
