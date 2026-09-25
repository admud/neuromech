import asyncio
import json
import time

from websockets.asyncio.server import serve

from hub.sim.robot_sim import RobotSim


def test_robot_hello_frames_pose_and_watchdog():
    asyncio.run(_exercise_robot())


async def _exercise_robot():
    observations = []
    async def handler(ws):
        hello = json.loads(await ws.recv())
        assert hello["name"] == "sim"
        await ws.send(json.dumps({"type": "cmd", "seq": 1, "vx": 0, "vy": 1, "ttl_ms": 200}))
        deadline = time.monotonic() + 0.7
        while time.monotonic() < deadline:
            msg = await asyncio.wait_for(ws.recv(), 0.3)
            if isinstance(msg, bytes):
                assert msg.startswith(b"\xff\xd8")
                observations.append("frame")
            else:
                observations.append(json.loads(msg))
        await ws.close()

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        robot = RobotSim(hub=f"ws://127.0.0.1:{port}", fps=10)
        from websockets.asyncio.client import connect
        async with connect(robot.hub) as ws:
            await robot.session(ws)
    telemetry = [m for m in observations if isinstance(m, dict) and m.get("type") == "telemetry"]
    assert "frame" in observations
    assert any(m["y"] > 0 for m in telemetry)
    assert any(m["watchdog_stopped"] and m["vy"] == 0 for m in telemetry)
