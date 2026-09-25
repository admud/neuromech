# Demo-day runbook: headset + iPhone test

The robot is still **virtual**: the 3D sim embedded in the laptop dashboard is
the robot, and its camera is the video on the phone. Everything runs from the
repo root on the laptop, with the venv Python.

## 0. Before you start (5 min)

- Laptop on mains power, and the lid stays open. The dashboard window must stay visible: a
  minimised or background tab freezes the virtual robot and the phone's
  video ("Sim hidden" banner).
- iPhone:
  - *Settings → Apps → Safari → Advanced → Feature Flags →*
    **"Prefer Page Rendering Updates near 60fps" OFF**. Without this, Safari caps the flicker at 60 fps.
  - Low Power Mode **off**, Auto-Lock **Never**, brightness **max**, True Tone and Night Shift off.
  - Silence notifications (Focus mode). A banner covering a target breaks that target's flicker.
- Windows Firewall: the phone must be able to reach the laptop on TCP 8765.
  The first time `python` listens, Windows asks: tick **Public** too. If you missed it,
  run this once in an admin PowerShell:
  ```
  netsh advfirewall firewall add rule name="NeuroMech hub" dir=in action=allow protocol=TCP localport=8765 profile=any
  ```

## 1. Headset

1. Plug in the Cyton USB dongle. Its switch must be on **GPIO6**. Turn the Cyton board on (PC side).
2. Put the headset on. The decoder uses **O1, O2, P7, P8** (back of the head), so get those right first.
3. Check contact (finds the dongle's COM port by itself):
   ```
   cd control
   .venv\Scripts\python contact_viz.py
   ```
   - Traces should be wiggly, not flat or wandering; the spectrum should fall off with frequency
     (1/f) and show little 50 Hz.
   - Press **A** for the alpha test (8 s eyes open, then 8 s eyes closed). O1/O2 alpha (~10 Hz) must
     rise clearly with eyes closed. If it doesn't, those electrodes aren't on the scalp: fix them now.
   - Close the window (Q) before starting the hub. Only one program can hold the dongle.

## 2. Start the hub

```
control\.venv\Scripts\python -m hub
```
- It finds the dongle, settles 3 s, then prints `Phone:` and `Dashboard:` URLs, one per network
  adapter. The **192.168.x.x** (WiFi) one is usually right. The 172.x ones are Docker/WSL.
- The default decoder margin is **0.08** (see Measurements for why).
- Useful flags: `--port COM8` (skip auto-detect), `--margin 0.1`, `--dwell 3`, `--speed 0.3`,
  `--freqs 11,14,17,20`, `--model <calibration.npz>`.

## 3. Dashboard (laptop)

Open `http://localhost:8765/dashboard/` in Chrome, in a normal visible window.
- **Virtual robot** switch ON (default). The sim appears and connects as robot `virtual`. Links panel:
  robot connected, video about 20 fps.
- The EEG row shows `cyton`, the port, and per-channel quality. A channel with a red `railed` flag
  isn't making contact.
- Never open `/twin/` in a second tab or browser: two virtual robots fight over the one robot slot.

## 4. Phone

1. Join the **same WiFi** as the laptop.
2. In Safari, open the `Phone:` URL the hub printed, e.g. `http://192.168.0.204:8765/phone/`.
3. Optional: *Share → Add to Home Screen*, and launch from there. That hides Safari's bars. Check
   the fps readout both ways and use whichever shows ~120.
4. Landscape. The status line shows the **fps**. It must read **~120**. The dashboard's Links
   panel shows the same number, in red if it's below 100.
   - If it's ~60, the Feature Flag is still on, or Low Power Mode is on.
   - A small fps dip when the video starts is fine. Drops that persist mean the phone is throttling
     (hot, low battery).

## 5. Drive

1. **Arm**: long-press **HOLD TO ARM** (bottom-left, 1 s ring) on the phone, or press ARM on the
   dashboard. Arming is refused while the EEG isn't flowing.
2. **Look at a bar** to drive: top = forward, bottom = back, left = strafe left, right = strafe right.
   - Expect the robot to start **~1.5 s** after you fix your gaze.
   - The dashboard's decoder panel shows the winner and dwell pips filling.
3. **Look at the video** (the middle) to stop. It takes **~2.4 s** to stop: the decoder's 3 s window
   still holds the old flicker. Plan for that near walls.
4. **STOP** at any time:
   - phone: **STOP** (bottom-right, fires on touch);
   - dashboard: **STOP** button, **Space** or **Esc** (they also work while the sim has focus).
     In full-screen sim, Esc only exits full screen: use **Space**.
5. Keyboard override (arrows/WASD on the dashboard) drives only while armed and beats the BCI.
   Use it to reposition the robot.

The robot also stops by itself and the hub disarms (the reason is shown on both screens) when:
- the phone page closes or goes silent for 3 s (`phone_lost`);
- the phone locks or leaves Safari (the page sends STOP, shown as `user`);
- the robot goes away (`robot_lost`);
- the EEG stops for 1.5 s, or the hub itself froze (`eeg_stall`).

Re-arming is always a deliberate long-press or ARM.

## 6. Tuning live (dashboard → Tuning)

- **Margin** 0.08 by default. Raise it to 0.10 if the robot creeps while you look at the video;
  lower it to 0.06 if targets are hard to trigger.
- **Dwell** 2 by default. 3 gives fewer false moves but adds 0.25 s before moving.
- **Window** 3 s by default. 2 s reacts and stops faster but is noisier. Keep it at 2 s or more with a real headset.
- **Freqs**: the phone switches on the next frame. Keep them 5–40 Hz, away from alpha (~10 Hz),
  and free of shared harmonics (the dashboard warns you).
- **Speed** 0.3 by default.

## Fallbacks

- **Phone can't load the page** but the laptop can: the venue WiFi isolates clients.
  - Turn on the iPhone's **Personal Hotspot** and join the laptop to it.
  - Restart the hub; it prints a new `Phone:` URL, usually `172.20.10.x`.
  - Open that on the phone. Safari may take a few seconds on the first load.
- **"OpenBCI dongle not found"** / **"Several possible OpenBCI dongles"**: the message lists every
  port seen. Pass the right one with `--port COMx` (Device Manager → Ports: "USB Serial Port").
  COM3/COM4 are Bluetooth and are never the headset.
- **No headset available**: `python -m hub --device sim`. The dashboard then shows sim-gaze buttons
  (and keys 1–4, 0) that stand in for your eyes.

## Troubleshooting

- **Hub exits with "could not open cyton on COMx"**
  - Something else holds the port: close contact_viz / ssvep_bci / the OpenBCI GUI.
  - The board is off, or the dongle isn't in GPIO6.
- **Arm does nothing, EEG row red / `eeg_stall`**
  - The Cyton isn't streaming: battery, board switch, or dongle range.
  - Restart the hub.
- **Robot creeps while looking at the video**
  - Raise the margin (0.10), or dwell to 3.
  - Check that O1/O2 contact is good (alpha test).
- **Target never triggers**
  - Look for a red `railed` channel or poor contact.
  - Check the phone fps is ~120.
  - Hold your gaze steadily for 2 s.
  - Try lowering the margin to 0.06.
- **Phone fps ~60**
  - Safari Feature Flag still on, or Low Power Mode on.
  - Reload after changing either.
- **Phone shows DISCONNECTED**
  - The hub is down, or the WiFi changed: it reconnects by itself within a few seconds.
  - Otherwise check the firewall.
- **Phone video frozen or black, flicker fine**
  - The dashboard window is minimised or behind another tab ("Sim hidden"): bring it to the front.
  - Robot not connected: check the Virtual robot switch.
- **Robot shows "replaced" / keeps dropping**
  - Two robots are connected: a second `/twin/` tab, or `robot_sim` running while the switch is ON.
  - Close the extra one, then toggle the switch OFF and ON.
- **Dashboard warning "share a harmonic"**: pick different freqs. CCA can't separate those two targets.
- **Dashboard warning "synthetic board"**: you started `--device synthetic`. It's a plumbing test
  whose C4 carries a 20 Hz sine, so it always "looks right". Use `--device sim` instead.

## Measurements (simulation)

Laptop: 16 cores, Intel GPU. Hub `--device sim`, window 3 s, dwell 2, margin 0.08 unless stated. From
`e2e/measure.py`, `e2e/load_measure.mjs` and @main's runs.

- **Gaze → motion:**
  - median 1.50 s (range 0.95–1.78 s, 12 trials, no misses);
  - switching directly from one target to another takes longer (~3.7 s), because the old one must
    leave the window first.
- **Look-away → stop:** median 2.38 s (range 2.09–2.61 s).
- **False motion while looking at the video:**
  - margin 0.06: 9.7% of the time (@main);
  - margin 0.08: 0.5% (@main) to 3.0% (Phase 2, 3 short episodes in 60 s). It varies run to run.
  - The simulator's noise model is a guess; re-check with the real headset and tune the margin.
- **Video, robot → hub → viewer relay:** median 3.5 ms, p95 5.6 ms.
  - Glass-to-glass wasn't measured with a real camera.
  - The virtual robot's FPV pipeline adds ~100–150 ms (GPU readback + JPEG, 1E notes), plus the
    phone's decode.
- **Video frame rate into the hub** (virtual robot FPV):
  - 19–20 fps with the dashboard alone;
  - 13–19 fps when a headless phone page also runs on the same laptop GPU. The real iPhone decodes on its
    own hardware.
- **Phone flicker:**
  - headed Chrome at 120 Hz: 120 fps, p95 8.4 ms, 0 dropped (1C);
  - on-screen frequencies measured from the drawn frames match the config exactly, including after
    a live change to 11.5/13.5/16.5/19.5 Hz;
  - under three headless Chromes sharing the laptop GPU: 83 fps (not representative).
  - **Not yet measured on the iPhone:** read its fps readout at step 4.
- **Hub CPU** (dashboard + phone + sim EEG + decoding): median 25% of one core, max 37%.
- **Frozen hub** (process suspended while driving):
  - `robot_sim` stops 0.49 s in and the virtual robot 0.44 s in (`ttl_ms` 500);
  - on resume the hub is disarmed (`eeg_stall`).
