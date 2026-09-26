"""The bridge is exercised only against localhost UDP and fake hub sockets."""

import asyncio
import json
import socket
import time

from websockets.asyncio.server import serve

from hub.ugv.bridge import UgvBridge, direction_for


class UdpRecorder(asyncio.DatagramProtocol):
    def __init__(self):
        self.events = []

    def datagram_received(self, data, address):
        self.events.append((time.monotonic(), data.decode("ascii")))

    def words(self):
        return [word for _, word in self.events]


async def eventually(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.005)
    assert predicate()


async def setup_bridge(repeat=0.5, video="none"):
    loop = asyncio.get_running_loop()
    recorder = UdpRecorder()
    transport, _ = await loop.create_datagram_endpoint(lambda: recorder,
                                                        local_addr=("127.0.0.1", 0))
    udp_port = transport.get_extra_info("sockname")[1]
    connected = loop.create_future()
    connections = []
    incoming = []

    async def handler(ws):
        hello = json.loads(await ws.recv())
        connections.append(ws)
        if not connected.done():
            connected.set_result((ws, hello))
        async for raw in ws:
            incoming.append(raw if isinstance(raw, bytes) else json.loads(raw))

    server = await serve(handler, "127.0.0.1", 0)
    ws_port = server.sockets[0].getsockname()[1]
    bridge = UgvBridge(hub=f"ws://127.0.0.1:{ws_port}", host="127.0.0.1",
                       port=udp_port, repeat=repeat, video=video)
    bridge.test_connections = connections
    runner = asyncio.create_task(bridge.run())
    ws, hello = await asyncio.wait_for(connected, 2)
    await asyncio.sleep(0.06)  # drain startup STOP datagrams before test recording
    return bridge, runner, server, transport, recorder, ws, hello, incoming


async def teardown_bridge(runner, server, transport):
    runner.cancel()
    await asyncio.gather(runner, return_exceptions=True)
    await asyncio.sleep(0.06)  # receive the exit STOP burst
    server.close()
    await server.wait_closed()
    transport.close()


def test_direction_mapping():
    assert direction_for(0.3, 0) == "FWD"
    assert direction_for(-0.3, 0) == "BACK"
    assert direction_for(0, 0.3) == "LEFT"
    assert direction_for(0, -0.3) == "RIGHT"
    assert direction_for(0, 0) == "STOP"


def test_dry_run_prints_without_udp(capsys):
    listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    listener.bind(("127.0.0.1", 0))
    bridge = UgvBridge(host="127.0.0.1", port=listener.getsockname()[1],
                       video="none", dry_run=True)
    try:
        bridge.on_command({"vx": 0.3, "vy": 0, "ttl_ms": 500})
        bridge.emergency_stop()
        output = capsys.readouterr().out
        assert " FWD" in output
        assert output.count(" STOP") == 3
        listener.settimeout(0.05)
        try:
            listener.recvfrom(32)
            raise AssertionError("dry-run sent a UDP packet")
        except socket.timeout:
            pass
    finally:
        bridge.socket.close()
        listener.close()


def test_udp_mapping_change_repeat_and_stop_burst():
    asyncio.run(_exercise_udp_mapping())


async def _exercise_udp_mapping():
    bridge, runner, server, transport, recorder, ws, hello, incoming = await setup_bridge(repeat=0.3)
    try:
        assert hello["type"] == "hello" and hello["name"] == "ugv"
        assert hello["video"]["fps"] == 0
        await asyncio.sleep(0.08)
        recorder.events.clear()  # startup STOP burst

        for vx, vy, expected in ((0.3, 0, "FWD"), (-0.3, 0, "BACK"),
                                 (0, 0.3, "LEFT"), (0, -0.3, "RIGHT")):
            await ws.send(json.dumps({"type": "cmd", "vx": vx, "vy": vy, "ttl_ms": 500}))
            await eventually(lambda: recorder.words() and recorder.words()[-1] == expected)
        assert recorder.words() == ["FWD", "BACK", "LEFT", "RIGHT"]

        await ws.send(json.dumps({"type": "cmd", "vx": 0, "vy": 0, "ttl_ms": 500}))
        await eventually(lambda: recorder.words().count("STOP") >= 3)
        stop_times = [when for when, word in recorder.events if word == "STOP"][:3]
        assert all(0.01 <= b - a <= 0.06 for a, b in zip(stop_times, stop_times[1:]))
        assert recorder.words()[-3:] == ["STOP"] * 3
        await ws.send(json.dumps({"type": "ping", "t_hub": 123.4}))
        await eventually(lambda: any(isinstance(m, dict) and m.get("type") == "pong"
                                     for m in incoming))
        assert next(m for m in incoming if isinstance(m, dict) and m.get("type") == "pong")["t_hub"] == 123.4
        await eventually(lambda: any(isinstance(m, dict) and m.get("type") == "telemetry"
                                     for m in incoming))
        assert bridge.last_udp_command == "STOP"
    finally:
        await teardown_bridge(runner, server, transport)


def test_repeat_watchdog_video_and_exit_stop():
    asyncio.run(_exercise_repeat_watchdog())


async def _exercise_repeat_watchdog():
    bridge, runner, server, transport, recorder, ws, hello, incoming = await setup_bridge(
        repeat=0.2, video="test")
    try:
        assert hello["video"] == {"w": 640, "h": 480, "fps": 10}
        await eventually(lambda: any(isinstance(m, bytes) and m.startswith(b"\xff\xd8")
                                     for m in incoming))
        recorder.events.clear()
        await ws.send(json.dumps({"type": "cmd", "vx": 0.4, "vy": 0, "ttl_ms": 500}))
        await eventually(lambda: recorder.words().count("FWD") == 1)
        # The hub resends at 10 Hz; the UDP bridge must not echo each one.
        for _ in range(2):
            await asyncio.sleep(0.08)
            await ws.send(json.dumps({"type": "cmd", "vx": 0.4, "vy": 0, "ttl_ms": 500}))
        assert recorder.words().count("FWD") == 1
        await eventually(lambda: recorder.words().count("FWD") >= 2, timeout=0.3)
        forward_times = [when for when, word in recorder.events if word == "FWD"]
        assert 0.18 <= forward_times[1] - forward_times[0] <= 0.28
        await eventually(lambda: bridge.watchdog_stopped, timeout=0.8)
        await eventually(lambda: recorder.words().count("STOP") >= 3)
        assert bridge.direction == "STOP"
        await eventually(lambda: any(isinstance(m, dict) and m.get("type") == "telemetry"
                                     and m.get("watchdog_stopped")
                                     and m.get("last_udp_command") == "STOP"
                                     for m in incoming))
        count = recorder.words().count("STOP")
        await eventually(lambda: recorder.words().count("STOP") > count, timeout=1.2)
        assert recorder.words()[-1] == "STOP"
    finally:
        await teardown_bridge(runner, server, transport)
        assert recorder.words()[-3:] == ["STOP"] * 3


def test_replacement_exits_with_stop():
    asyncio.run(_exercise_replacement())


async def _exercise_replacement():
    bridge, runner, server, transport, recorder, ws, hello, incoming = await setup_bridge()
    try:
        recorder.events.clear()
        await ws.send(json.dumps({"type": "cmd", "vx": 0.3, "vy": 0, "ttl_ms": 500}))
        await eventually(lambda: "FWD" in recorder.words())
        await ws.close(code=4001, reason="replaced")
        await asyncio.wait_for(runner, 1)
        await eventually(lambda: recorder.words().count("STOP") >= 3)
        assert recorder.words() == ["FWD", "STOP", "STOP", "STOP"]
    finally:
        await teardown_bridge(runner, server, transport)


def test_unexpected_exception_exits_with_stop():
    asyncio.run(_exercise_exception_stop())


async def _exercise_exception_stop():
    bridge, runner, server, transport, recorder, ws, hello, incoming = await setup_bridge(video="test")
    try:
        recorder.events.clear()
        await ws.send(json.dumps({"type": "cmd", "vx": 0.3, "vy": 0, "ttl_ms": 500}))
        await eventually(lambda: "FWD" in recorder.words())

        def broken_frame():
            raise RuntimeError("camera failed")

        bridge.camera.get_frame = broken_frame
        try:
            await asyncio.wait_for(runner, 1)
            raise AssertionError("bridge should propagate camera failure")
        except RuntimeError as exc:
            assert str(exc) == "camera failed"
        await eventually(lambda: recorder.words().count("STOP") >= 3)
        assert recorder.words()[-3:] == ["STOP"] * 3
    finally:
        await teardown_bridge(runner, server, transport)


def test_watchdog_rejects_late_motion_until_new_session_sees_zero():
    asyncio.run(_exercise_watchdog_recovery())


async def _exercise_watchdog_recovery():
    bridge, runner, server, transport, recorder, ws, hello, incoming = await setup_bridge(video="none")
    try:
        recorder.events.clear()
        await ws.send(json.dumps({"type": "cmd", "vx": 0.3, "vy": 0, "ttl_ms": 500}))
        await eventually(lambda: "FWD" in recorder.words())
        await eventually(lambda: bridge.watchdog_fired.is_set(), timeout=0.8)
        await eventually(lambda: recorder.words().count("STOP") >= 3)
        forward_count = recorder.words().count("FWD")
        # A stale packet from the timed-out stream cannot restart movement.
        bridge.on_command({"type": "cmd", "vx": 0.3, "vy": 0, "ttl_ms": 500})
        assert recorder.words().count("FWD") == forward_count
        await eventually(lambda: len(bridge.test_connections) >= 2, timeout=2)
        fresh_ws = bridge.test_connections[-1]
        await fresh_ws.send(json.dumps({"type": "cmd", "vx": 0.3, "vy": 0, "ttl_ms": 500}))
        await asyncio.sleep(0.1)
        assert recorder.words().count("FWD") == forward_count
        assert bridge.recovery_requires_zero
        await fresh_ws.send(json.dumps({"type": "cmd", "vx": 0, "vy": 0, "ttl_ms": 500}))
        await eventually(lambda: not bridge.recovery_requires_zero)
        await fresh_ws.send(json.dumps({"type": "cmd", "vx": 0.3, "vy": 0, "ttl_ms": 500}))
        await eventually(lambda: recorder.words().count("FWD") > forward_count)
    finally:
        await teardown_bridge(runner, server, transport)
