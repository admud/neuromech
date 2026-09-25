# NeuroMech

UI/UX interface for NeuroMech, our project for the [Singapore Defense Tech Hackathon (SDTH) 2026](https://luma.com/sdth-2026).

## Repository layout

- [`control/`](control/) — SSVEP brain-computer interface (OpenBCI Cyton + EEG-ExPy) that turns EEG into direction commands. See [`control/README.md`](control/README.md).
- [`hub/`](hub/) — PC hub (`python -m hub`): BCI engine and safety arbiter, WebSockets for the phone, dashboard, video and robot.
- [`web/`](web/) — pages served by the hub: `phone/` (flicker targets + robot video), `dashboard/` (operator), `twin/` (3D virtual robot).
- [`e2e/`](e2e/) — end-to-end scenario scripts run in simulation.
- [`plan/`](plan/) — build plan, the protocol contract, and the demo-day [runbook](plan/runbook.md).
