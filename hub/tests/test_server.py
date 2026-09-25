import time

from fastapi.testclient import TestClient

import hub.server as server
from hub.server import create_app
from hub.stub_engine import StubEngine


def receive_type(ws, kind, limit=20):
    for _ in range(limit):
        msg = ws.receive_json()
        if msg.get("type") == kind:
            return msg
    raise AssertionError(f"No {kind} in {limit} messages")


def until(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    assert predicate()


def test_health_and_phone_config_arm():
    engine = StubEngine()
    with TestClient(create_app(engine)) as client:
        assert client.get("/api/health").json() == {"ok": True}
        assert client.get("/", follow_redirects=False).headers["location"] == "/phone/"
        assert client.get("/phone/").status_code == 200
        assert client.get("/phone/phone.js").headers["content-type"].startswith("text/javascript")
        assert client.get("/twin/").status_code == 200
        with client.websocket_connect("/ws/phone") as phone:
            assert phone.receive_json()["type"] == "config"
            phone.send_json({"type": "arm", "armed": True})
            state = receive_type(phone, "state")
            assert state["phone"]["connected"] is True
            # The state broadcast may race the incoming arm, so poll a later state.
            for _ in range(5):
                if state["armed"]:
                    break
                state = receive_type(phone, "state")
            assert state["armed"] is True
        assert engine.phone is False
        assert engine.reason == "phone_lost"


def test_config_rebroadcast():
    with TestClient(create_app(StubEngine())) as client:
        with client.websocket_connect("/ws/phone") as phone:
            phone.receive_json()
            with client.websocket_connect("/ws/dashboard") as dashboard:
                dashboard.receive_json()
                dashboard.send_json({"type": "set_config", "freqs": {"up": 12.0}})
                assert receive_type(dashboard, "config")["targets"][0]["freq"] == 12.0
                assert receive_type(phone, "config")["targets"][0]["freq"] == 12.0


def test_disconnect_does_not_stop_state_stream():
    with TestClient(create_app(StubEngine())) as client:
        with client.websocket_connect("/ws/phone") as survivor:
            survivor.receive_json()
            with client.websocket_connect("/ws/phone") as departing:
                departing.receive_json()
            first = receive_type(survivor, "state")
            second = receive_type(survivor, "state")
            assert second["t_hub"] > first["t_hub"]
            assert second["phone"]["connected"] is True


def test_silent_phone_is_disconnected_and_disarms(monkeypatch):
    monkeypatch.setattr(server, "IDLE_TIMEOUT_S", 0.25)
    engine = StubEngine()
    with TestClient(create_app(engine)) as client:
        with client.websocket_connect("/ws/phone") as phone:
            phone.receive_json()
            phone.send_json({"type": "arm", "armed": True})
            until(lambda: engine.armed)
            until(lambda: not engine.phone)
            assert engine.armed is False
            assert engine.reason == "phone_lost"


def test_silent_robot_is_disconnected_and_disarms(monkeypatch):
    monkeypatch.setattr(server, "IDLE_TIMEOUT_S", 0.25)
    engine = StubEngine()
    with TestClient(create_app(engine)) as client:
        with client.websocket_connect("/ws/robot") as robot:
            robot.send_json({"type": "hello", "client": "robot", "name": "sim"})
            robot.send_json({"type": "telemetry", "vx": 0, "vy": 0,
                             "watchdog_stopped": False})
            until(lambda: engine.robot)
            engine.handle({"type": "arm", "armed": True}, "dashboard")
            until(lambda: not engine.robot)
            assert engine.armed is False
            assert engine.reason == "robot_lost"


def test_robot_commands_video_and_replacement():
    with TestClient(create_app(StubEngine())) as client:
        with client.websocket_connect("/ws/video") as viewer:
            with client.websocket_connect("/ws/robot") as first:
                cmd1 = receive_type(first, "cmd")
                cmd2 = receive_type(first, "cmd")
                assert cmd2["seq"] > cmd1["seq"]
                assert cmd1["ttl_ms"] == 500
                frame = b"\xff\xd8test\xff\xd9"
                first.send_bytes(frame)
                assert viewer.receive_bytes() == frame
                first.send_bytes(b"old")
                first.send_bytes(b"new")
                with client.websocket_connect("/ws/video") as late_viewer:
                    assert late_viewer.receive_bytes() == b"new"
                with client.websocket_connect("/ws/robot") as second:
                    assert receive_type(second, "cmd")["seq"] > cmd2["seq"]
                    second.send_json({"type": "hello", "name": "sim", "client": "robot"})
                    with client.websocket_connect("/ws/dashboard") as dashboard:
                        dashboard.receive_json()
                        assert receive_type(dashboard, "state")["robot"]["connected"] is True
                # Closing the old socket may already have surfaced to TestClient.


def test_video_relay_never_sends_a_stale_frame():
    import asyncio

    from hub import video as videomod

    class Viewer:
        def __init__(self):
            self.got = []

        async def send_bytes(self, b):
            self.got.append(b)

    async def scenario():
        relay = videomod.VideoRelay()
        await relay.publish(b"old")
        relay.frame_t -= videomod.MAX_AGE_S + 0.5      # the robot left a while ago
        viewer = Viewer()
        task = asyncio.create_task(relay.serve(viewer))
        await asyncio.sleep(0.05)
        stale = list(viewer.got)
        await relay.publish(b"new")
        await asyncio.sleep(0.05)
        task.cancel()
        return stale, viewer.got

    stale, got = asyncio.run(scenario())
    assert stale == [] and got == [b"new"]
