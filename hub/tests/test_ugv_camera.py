"""The rover camera path: the motion freeze, the threaded reader against a
local MJPEG server that stalls like a browned-out camera, and the bridge
end to end against a fake hub. Nothing is sent to the real rover."""

import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np

from hub.tests.test_ugv_bridge import eventually, setup_bridge, teardown_bridge
from hub.ugv.camera import CameraFeed, FreezeGate, parse_source


def test_parse_source():
    assert parse_source("1") == 1
    assert parse_source("http://NeuroMech.local:8000/stream.mjpg") == "http://NeuroMech.local:8000/stream.mjpg"


def test_gate_holds_the_last_frame_from_before_the_drive():
    gate = FreezeGate(settle_s=1.0, resend_s=0.5)
    assert gate.step(0.0, False, b"a", 0.0) == b"a"
    assert gate.step(0.1, False, b"b", 0.1) == b"b"
    # Motors start at 0.2: frames from then on are the browned-out camera.
    assert gate.step(0.2, True) is None
    assert gate.frozen(0.2)
    assert gate.step(0.3, True, b"lost", 0.3) is None
    assert gate.step(0.61, True) == b"b"            # re-sent every 0.5 s
    assert gate.step(0.7, True, b"lost", 0.7) is None
    assert gate.step(1.12, True) == b"b"
    # Stop at 1.5: still frozen for the 1 s settle, then live again.
    assert gate.step(1.5, False, b"lost", 1.5) is None
    assert gate.step(1.62, False) == b"b"                        # re-sends continue
    assert gate.step(1.9, False, b"recovering", 1.9) is None
    assert gate.step(2.12, False, b"recovering", 2.12) == b"b"   # the re-send, not the new frame
    assert gate.frozen(2.4)
    assert gate.step(2.5, False, b"c", 2.5) == b"c"
    assert not gate.frozen(2.5)
    assert gate.step(3.5, False) is None             # no re-sends while live


def test_gate_keeps_a_frame_that_arrived_before_the_drive():
    gate = FreezeGate(settle_s=1.0)
    gate.step(0.0, False, b"a", 0.0)
    # The frame arrived at 0.19 but is only picked up after the drive began at 0.2.
    gate.step(0.2, True)
    assert gate.step(0.21, True, b"b", 0.19) == b"b"
    assert gate.held == b"b"


def test_gate_disabled_passes_everything():
    gate = FreezeGate(enabled=False)
    assert gate.step(0.0, True, b"a", 0.0) == b"a"
    assert not gate.frozen(0.0)
    assert gate.step(1.0, True) is None


def test_gate_with_no_settle_resumes_at_once():
    gate = FreezeGate(settle_s=0.0)
    gate.step(0.0, True)
    assert gate.step(1.0, False, b"a", 1.0) == b"a"


def jpeg(value):
    image = np.full((240, 320, 3), value, np.uint8)
    return cv2.imencode(".jpg", image)[1].tobytes()


class Mjpeg:
    """A local MJPEG server, like a Pi camera stream. `stall` stops frames
    without closing the connection; `stop` kills it."""

    def __init__(self):
        self.value = 40
        self.stall = threading.Event()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                self.end_headers()
                try:
                    while True:
                        if owner.stall.is_set():
                            time.sleep(0.05)
                            continue
                        data = jpeg(owner.value)
                        self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n"
                                         b"Content-Length: %d\r\n\r\n" % len(data) + data + b"\r\n")
                        time.sleep(0.05)
                except (ConnectionError, OSError):
                    pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.url = "http://127.0.0.1:%d/stream.mjpg" % self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


def wait_for(predicate, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def mean_of(data):
    return float(cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE).mean())


def test_feed_reads_an_mjpeg_stream_and_survives_a_stall():
    server = Mjpeg()
    feed = CameraFeed(server.url).start()
    try:
        assert wait_for(lambda: feed.latest()[0] >= 3, 10), "no frames from the MJPEG stream"
        assert abs(mean_of(feed.latest()[1]) - 40) < 3
        # Brown-out: the stream goes quiet for 3 s, longer than the 2 s read timeout.
        server.stall.set()
        time.sleep(0.2)
        seq = feed.latest()[0]
        time.sleep(3.0)
        assert feed.latest()[0] <= seq + 1
        server.value = 200
        server.stall.clear()
        # The reader reopens or resumes by itself.
        assert wait_for(lambda: feed.latest()[1] is not None and mean_of(feed.latest()[1]) > 190, 10)
    finally:
        feed.stop()
        server.stop()
    assert not feed.thread.is_alive()


def test_bridge_freezes_the_video_while_driving():
    asyncio.run(_exercise_freeze())


async def _exercise_freeze():
    bridge, runner, server, transport, recorder, ws, hello, incoming = await setup_bridge(
        repeat=0.2, video="test")
    bridge.gate.settle_s = 0.6
    frames = lambda: [m for m in incoming if isinstance(m, bytes)]
    frozen = lambda: [m["video_frozen"] for m in incoming
                      if isinstance(m, dict) and m.get("type") == "telemetry"]
    try:
        await eventually(lambda: len(frames()) >= 3)
        assert frozen()[-1] is False
        drive = asyncio.create_task(_drive(ws, 1.2))
        await eventually(lambda: "FWD" in recorder.words())
        start = len(frames())
        await drive
        during = frames()[start:]
        # Every frame sent while driving is the same held picture, re-sent
        # at the live 10 fps.
        assert 9 <= len(during) <= 14, len(during)
        assert len(set(during)) == 1
        assert True in frozen()
        # Like the hub: zero commands keep coming at 10 Hz after the stop.
        idle = asyncio.create_task(_drive(ws, 2.0, vx=0))
        await eventually(lambda: recorder.words().count("STOP") >= 3)
        stopped_at = time.monotonic()
        await asyncio.sleep(0.4)                     # inside the settle: still held
        assert len(set(frames()[start:])) == 1
        await eventually(lambda: frames()[-1] != during[-1], timeout=1.5)   # live again
        assert 0.5 <= time.monotonic() - stopped_at <= 0.8
        await eventually(lambda: frozen()[-1] is False, timeout=0.5)
        await idle
    finally:
        await teardown_bridge(runner, server, transport)


async def _drive(ws, seconds, vx=0.3):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        await ws.send(json.dumps({"type": "cmd", "vx": vx, "vy": 0, "ttl_ms": 500}))
        await asyncio.sleep(0.1)


def test_bridge_no_freeze_streams_while_driving():
    asyncio.run(_exercise_no_freeze())


async def _exercise_no_freeze():
    bridge, runner, server, transport, recorder, ws, hello, incoming = await setup_bridge(
        repeat=0.2, video="test")
    bridge.gate.enabled = False
    frames = lambda: [m for m in incoming if isinstance(m, bytes)]
    try:
        await eventually(lambda: len(frames()) >= 2)
        start = len(frames())
        await _drive(ws, 1.0)
        during = frames()[start:]
        assert len(during) >= 8 and len(set(during)) == len(during)
        assert not any(m.get("video_frozen") for m in incoming
                       if isinstance(m, dict) and m.get("type") == "telemetry")
    finally:
        await teardown_bridge(runner, server, transport)
