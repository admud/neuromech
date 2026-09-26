"""Hub links for the desktop GUI, on an asyncio loop in a background thread.

- /ws/phone: the GUI is the operator display, so it speaks the phone
  protocol (hello, frame_stats, arm, ping; receives config/state/pong). The
  hub counts it as the phone: closing it disarms with `phone_lost`.
- /ws/dashboard: only to send `override` (keyboard drive), which the hub
  accepts from dashboard clients only.
- /ws/video: JPEG frames, handed to a callback (the decoder keeps the newest).

Every link reconnects every 1 s. /ws/phone and /ws/dashboard are dropped
after `stale_s` without a message (the hub sends `state` at 10 Hz), because
a WiFi drop can leave a socket half-open with no close event.
"""
import asyncio
import json
import threading
import time

import websockets

from .logic import DEFAULT_FREQS, TARGETS


class HubClient:
    def __init__(self, host="127.0.0.1:8765", on_video=None, stale_s=2.5,
                 hello_screen=None, retry_s=1.0):
        self.base = "ws://" + host
        self.on_video = on_video
        self.stale_s = stale_s
        self.retry_s = retry_s
        self.hello_screen = hello_screen or {}
        self._lock = threading.Lock()
        self._freqs = DEFAULT_FREQS
        self.config_id = None
        self._state = None
        self.state_rx = 0.0          # monotonic time the last state arrived
        self.rtt_ms = None
        self.open = {"phone": False, "dashboard": False, "video": False}
        self.connects = {"phone": 0, "dashboard": 0, "video": 0}
        self._queues = {}
        self._stopping = False
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run, name="hub-net", daemon=True)

    # ---- called from the render thread --------------------------------------

    def start(self):
        self.thread.start()
        return self

    @property
    def freqs(self):
        return self._freqs            # tuple swapped atomically; no lock needed

    @property
    def state(self):
        return self._state

    def hub_time(self, now):
        """Estimate of the hub's clock (state.t_hub) at monotonic time `now`,
        interpolated between the 10 Hz state messages. None without state."""
        s = self._state
        if not s or not isinstance(s.get("t_hub"), (int, float)):
            return None
        return s["t_hub"] + (now - self.state_rx)

    def send_phone(self, msg):
        return self._send("phone", msg)

    def send_dashboard(self, msg):
        return self._send("dashboard", msg)

    def stop(self, timeout=1.0):
        """Close every link (the hub then sees the phone go: `phone_lost`)."""
        self._stopping = True
        if self.loop.is_running():
            self.loop.call_soon_threadsafe(lambda: [t.cancel() for t in asyncio.all_tasks(self.loop)])
        self.thread.join(timeout)

    def flush(self, timeout=0.3):
        """Wait until queued outgoing messages have been written (used before quitting)."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if all(q.empty() for q in self._queues.values()):
                time.sleep(0.03)   # let the socket write finish
                return True
            time.sleep(0.01)
        return False

    def _send(self, route, msg):
        q = self._queues.get(route)
        if q is None or not self.open[route]:
            return False
        self.loop.call_soon_threadsafe(q.put_nowait, msg)
        return True

    # ---- network thread ------------------------------------------------------

    def _run(self):
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(asyncio.gather(
                self._link("phone"), self._link("dashboard"), self._video(),
                return_exceptions=True))
        finally:
            self.loop.close()

    async def _link(self, route):
        url = f"{self.base}/ws/{route}"
        while not self._stopping:
            tasks = []
            try:
                async with websockets.connect(url, max_size=None, ping_interval=None,
                                              open_timeout=3, close_timeout=0.3) as ws:
                    q = asyncio.Queue()
                    self._queues[route] = q
                    self.open[route] = True
                    self.connects[route] += 1
                    if route == "phone":
                        print("  hub link up (%s)" % url, flush=True)
                    tasks.append(asyncio.ensure_future(self._pump(ws, q)))
                    if route == "phone":
                        await ws.send(json.dumps({"type": "hello", "client": "desktop",
                                                  "ua": "hub.gui (psychopy)",
                                                  "screen": self.hello_screen}))
                        tasks.append(asyncio.ensure_future(self._pinger(ws)))
                    while True:
                        raw = await asyncio.wait_for(ws.recv(), timeout=self.stale_s)
                        if route == "phone" and isinstance(raw, str):
                            self._on_phone_message(raw)
            except asyncio.CancelledError:
                raise
            except Exception:
                pass   # refused, closed, stale (TimeoutError): reconnect
            finally:
                if route == "phone" and self.open[route] and not self._stopping:
                    print("  hub link DOWN, retrying every %.0f s" % self.retry_s, flush=True)
                self.open[route] = False
                self._queues.pop(route, None)
                for t in tasks:
                    t.cancel()
                if route == "phone":
                    self._state = None
                    self.rtt_ms = None
            await asyncio.sleep(self.retry_s)

    async def _pump(self, ws, q):
        while True:
            msg = await q.get()
            await ws.send(json.dumps(msg))
            q.task_done()

    async def _pinger(self, ws):
        while True:
            await ws.send(json.dumps({"type": "ping", "t_client": time.monotonic()}))
            await asyncio.sleep(2.0)

    def _on_phone_message(self, raw):
        try:
            m = json.loads(raw)
        except ValueError:
            return
        if not isinstance(m, dict):
            return
        kind = m.get("type")
        if kind == "state":
            self.state_rx = time.monotonic()
            self._state = m
        elif kind == "config" and isinstance(m.get("targets"), list):
            freqs = list(self._freqs)
            for t in m["targets"]:
                if isinstance(t, dict) and t.get("id") in TARGETS and isinstance(t.get("freq"), (int, float)):
                    freqs[TARGETS.index(t["id"])] = float(t["freq"])
            self._freqs = tuple(freqs)
            self.config_id = m.get("config_id")
        elif kind == "pong" and isinstance(m.get("t_client"), (int, float)):
            self.rtt_ms = round((time.monotonic() - m["t_client"]) * 1000)

    async def _video(self):
        url = f"{self.base}/ws/video"
        while not self._stopping:
            try:
                async with websockets.connect(url, max_size=None, ping_interval=None,
                                              open_timeout=3, close_timeout=0.3) as ws:
                    self.open["video"] = True
                    self.connects["video"] += 1
                    while True:
                        # No stale drop at 2.5 s: video is legitimately silent
                        # with no robot. A long silence still recycles it.
                        data = await asyncio.wait_for(ws.recv(), timeout=10.0)
                        if isinstance(data, bytes) and self.on_video:
                            self.on_video(data)
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            finally:
                self.open["video"] = False
            await asyncio.sleep(self.retry_s)
