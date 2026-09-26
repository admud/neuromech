"""Desktop GUI hub links (hub/gui/net.py) and video decoder against a fake hub."""
import asyncio
import json
import threading
import time

import cv2
import numpy as np
from websockets.asyncio.server import serve

from hub.gui.net import HubClient
from hub.gui.video import VideoDecoder


class FakeHub:
    """A minimal hub on its own thread: config + 10 Hz state on /ws/phone and
    /ws/dashboard, pong, one JPEG on /ws/video. With `silent_first`, the
    first phone connection goes quiet (but stays open) after one message."""

    def __init__(self, silent_first=False):
        self.silent_first = silent_first
        self.received = {"phone": [], "dashboard": []}
        self.phone_connections = 0
        self.port = None
        self._ready = threading.Event()
        self._stop = None
        self.thread = threading.Thread(target=lambda: asyncio.run(self._main()), daemon=True)
        self.thread.start()
        assert self._ready.wait(5)

    async def _main(self):
        self._stop = asyncio.Event()
        self.loop = asyncio.get_running_loop()
        async with serve(self._handler, "127.0.0.1", 0) as server:
            self.port = server.sockets[0].getsockname()[1]
            self._ready.set()
            await self._stop.wait()

    def close(self):
        self.loop.call_soon_threadsafe(self._stop.set)
        self.thread.join(5)

    async def _handler(self, ws):
        route = ws.request.path.rsplit("/", 1)[-1]
        if route == "video":
            ok, jpg = cv2.imencode(".jpg", np.full((48, 64, 3), (0, 0, 255), np.uint8))
            await ws.send(jpg.tobytes())
            await asyncio.sleep(30)
            return
        silent = False
        if route == "phone":
            self.phone_connections += 1
            silent = self.silent_first and self.phone_connections == 1
            await ws.send(json.dumps({"type": "config", "config_id": 4, "targets": [
                {"id": "up", "freq": 12.5}, {"id": "down", "freq": 14}, {"id": "left", "freq": 17},
                {"id": "right", "freq": 20}, {"id": "bogus", "freq": 99}]}))

        async def reader():
            async for raw in ws:
                m = json.loads(raw)
                self.received[route].append(m)
                if m.get("type") == "ping" and not silent:
                    await ws.send(json.dumps({"type": "pong", "t_client": m["t_client"], "t_hub": 0}))

        task = asyncio.ensure_future(reader())
        try:
            while not task.done():
                if not silent:
                    await ws.send(json.dumps({"type": "state", "armed": False, "disarm_reason": "startup"}))
                await asyncio.sleep(0.1)
        except Exception:
            pass
        finally:
            task.cancel()


def _wait(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_links_config_state_pong_sends_and_video():
    hub = FakeHub()
    dec = VideoDecoder().start()
    c = HubClient(f"127.0.0.1:{hub.port}", on_video=dec.push, hello_screen={"w": 2560, "h": 1440}).start()
    try:
        assert _wait(lambda: c.open["phone"] and c.open["dashboard"])
        assert _wait(lambda: c.freqs == (12.5, 14.0, 17.0, 20.0) and c.config_id == 4)
        assert _wait(lambda: c.state is not None and c.state["disarm_reason"] == "startup")
        assert _wait(lambda: c.rtt_ms is not None)
        hello = hub.received["phone"][0]
        assert hello["type"] == "hello" and hello["client"] == "desktop" and hello["screen"]["w"] == 2560

        assert c.send_phone({"type": "arm", "armed": True})
        assert c.send_dashboard({"type": "override", "direction": "up"})
        assert _wait(lambda: {"type": "arm", "armed": True} in hub.received["phone"])
        assert _wait(lambda: {"type": "override", "direction": "up"} in hub.received["dashboard"])
        # override goes only to the dashboard link, arm only to the phone link
        assert all(m.get("type") != "override" for m in hub.received["phone"])

        assert _wait(lambda: dec.seq >= 1)
        seq, frame = dec.latest()
        assert frame.shape == (48, 64, 3) and frame.dtype == np.uint8
        assert tuple(frame[0, 0]) == (255, 0, 0) or frame[0, 0, 0] > 240   # BGR red -> RGB red
    finally:
        c.stop()
        dec.stop()
        hub.close()


def test_half_open_socket_is_dropped_and_reconnects():
    hub = FakeHub(silent_first=True)
    c = HubClient(f"127.0.0.1:{hub.port}", stale_s=0.5, retry_s=0.2).start()
    try:
        assert _wait(lambda: c.open["phone"])
        # The first connection goes silent without closing; the client must
        # notice within stale_s and come back on a fresh socket.
        assert _wait(lambda: c.connects["phone"] >= 2, timeout=4)
        assert hub.phone_connections >= 2
        assert _wait(lambda: c.state is not None)
    finally:
        c.stop()
        hub.close()


def test_sends_fail_cleanly_with_no_hub():
    c = HubClient("127.0.0.1:1", retry_s=0.2).start()
    try:
        time.sleep(0.3)
        assert not c.send_phone({"type": "arm", "armed": False})
        assert not c.send_dashboard({"type": "override", "direction": None})
        assert c.state is None and not c.open["phone"]
    finally:
        c.stop()


def test_decoder_keeps_only_the_newest_frame():
    dec = VideoDecoder()      # not started: nothing decodes, so pushes pile up
    jpgs = []
    for v in (10, 120, 250):
        ok, jpg = cv2.imencode(".jpg", np.full((8, 8, 3), v, np.uint8))
        jpgs.append(jpg.tobytes())
        dec.push(jpgs[-1])
    assert dec.received == 3 and dec.dropped == 2
    dec.start()
    assert _wait(lambda: dec.seq == 1)
    time.sleep(0.1)
    seq, frame = dec.latest()
    assert seq == 1 and abs(int(frame[4, 4, 0]) - 250) < 6
    dec.push(b"not a jpeg")
    assert _wait(lambda: dec.errors == 1)
    assert dec.latest()[0] == 1
    dec.stop()
