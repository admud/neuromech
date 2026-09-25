# End-to-end tests (simulation)

Browser-level checks of the whole loop, driving real pages in headless
Chrome over the DevTools protocol (`cdp.mjs`, no npm deps; needs Node 22+
and Chrome at the default path). Each script expects a hub already running
on `HUB` (default `127.0.0.1:18931`):

```
control\.venv\Scripts\python -m hub --device sim --http-port 18931 --host 127.0.0.1
node e2e/integration.mjs          # needs a freshly started hub (checks disarm_reason "startup")
```

- `integration.mjs`: dashboard (virtual robot) + phone. Startup, arm, gaze
  up/left moves the robot, look-away stops it, Space STOPs, keyboard override,
  wall collision, `phone_lost`, `robot_lost`. Scenarios 1–7, 12.
- `twin_more.mjs`: look-away false motion vs margin, Esc inside the sim
  iframe, hub **killed** while driving. It restarts the hub at the end.
- `freeze_twin.mjs`: hub **frozen** (suspended, `suspend.py`) while the
  virtual robot drives; the robot must stop and the hub resume disarmed. Scenario 8.
- `freeze_robot_sim.py <port> <hub pid> [secs]`: the same with `robot_sim`.
- `s9_freqs.mjs`: new freqs from the dashboard form. Checks the phone's measured
  on-screen flicker and that sim gaze decodes at the new freqs. Scenario 9.
- `s14_switch.mjs`: Virtual robot switch vs `robot_sim`, full screen. Scenario 14.
- `measure.py`: gaze→motion / look-away→stop latency, false motion,
  video relay latency (`measure.py relay` for only the last).
- `load_measure.mjs`: phone fps/p95 and video fps with both pages open.

Results from Phase 2 are in [../plan/runbook.md](../plan/runbook.md#measurements-simulation).
