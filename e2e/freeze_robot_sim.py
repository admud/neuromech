"""Scenario 8: freeze the hub process (DebugActiveProcess) while robot_sim drives.

    python e2e/freeze_robot_sim.py <hub port> <hub pid> [freeze seconds]
"""
import asyncio, ctypes, json, subprocess, sys, time
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from hub.sim.robot_sim import RobotSim
import websockets

PORT = int(sys.argv[1]); PID = int(sys.argv[2])
k32 = ctypes.windll.kernel32

async def main():
    robot = RobotSim(hub=f"ws://127.0.0.1:{PORT}/ws/robot", fps=20)
    rt = asyncio.create_task(robot.run())
    log = []
    async def monitor():
        t0 = time.monotonic()
        while True:
            log.append((round(time.monotonic() - t0, 2), robot.vx, robot.watchdog_stopped, round(robot.x, 3)))
            await asyncio.sleep(0.05)
    mt = asyncio.create_task(monitor())
    d = await websockets.connect(f"ws://127.0.0.1:{PORT}/ws/dashboard")
    await asyncio.sleep(1.5)
    await d.send(json.dumps({"type": "arm", "armed": True}))
    for _ in range(10):
        await d.send(json.dumps({"type": "override", "direction": "up"})); await asyncio.sleep(0.15)
    print("before freeze vx", robot.vx, "wd", robot.watchdog_stopped)
    assert k32.DebugActiveProcess(PID), "suspend failed"
    k32.DebugSetProcessKillOnExit(False)
    tf = time.monotonic()
    # keep the dashboard client quiet; watch the robot for 4 s
    await asyncio.sleep(float(sys.argv[3]) if len(sys.argv) > 3 else 4.0)
    stopped_at = None
    for t, vx, wd, x in log:
        pass
    k32.DebugActiveProcessStop(PID)
    fr = [r for r in log if r[0] >= log[-1][0] - (float(sys.argv[3]) if len(sys.argv) > 3 else 4.0)]
    first_stop = next((r for r in fr if r[2] and r[1] == 0), None)
    print("freeze window samples:", fr[0], "...", fr[-1])
    print("first stopped sample:", first_stop, "freeze started at", round(fr[0][0], 2))
    gaps = [b[0] - a[0] for a, b in zip(log, log[1:])]
    print("max monitor gap s", max(gaps))
    await asyncio.sleep(3); print("after resume: connected robot state", robot.vx, robot.watchdog_stopped)
    s = None
    async for m in d:
        m = json.loads(m)
        if m["type"] == "state": s = m; break
    print("hub state after resume:", s["armed"], s["disarm_reason"], s["robot"]["connected"])
    mt.cancel(); rt.cancel()
asyncio.run(main())
