"""Translate /ws/robot velocity commands into the rover's UDP words."""

import asyncio
import json
import math
import socket
import time
from collections import deque
from contextlib import suppress

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from hub.sim.robot_sim import RobotSim

from .camera import CameraFeed, FreezeGate, parse_source


def direction_for(vx: float, vy: float) -> str:
    """The hub only sends one cardinal axis at a time; forward takes priority."""
    if vx > 0:
        return "FWD"
    if vx < 0:
        return "BACK"
    if vy > 0:
        return "LEFT"
    if vy < 0:
        return "RIGHT"
    return "STOP"


# --swap-lr: this rover strafes right on LEFT (its mecanum wheels are
# mirrored), so the bridge can send the other word.
SWAPPED = {"LEFT": "RIGHT", "RIGHT": "LEFT"}


def resolve_target(host: str, port: int) -> tuple[str, int]:
    try:
        addresses = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_DGRAM)
    except OSError as exc:
        raise ValueError(
            f"Could not resolve UGV host {host!r}: {exc}. "
            "Use --host with the Pi's IPv4 address."
        ) from exc
    if not addresses:
        raise ValueError(f"Could not resolve UGV host {host!r}; use --host with the Pi's IPv4 address.")
    return addresses[0][4]


class UgvBridge:
    def __init__(self, hub="ws://127.0.0.1:8765/ws/robot", host="NeuroMech.local",
                 port=5005, repeat=0.2, video="test", dry_run=False,
                 freeze_settle=1.0, no_freeze=False, swap_lr=False):
        if repeat <= 0 or not math.isfinite(repeat):
            raise ValueError("--repeat must be a positive finite number")
        if not 1 <= port <= 65535:
            raise ValueError("--port must be between 1 and 65535")
        if freeze_settle < 0 or not math.isfinite(freeze_settle):
            raise ValueError("--freeze-settle must be zero or more seconds")
        self.hub = hub
        self.target = resolve_target(host, port)
        self.repeat_s = repeat
        self.video = video
        self.dry_run = dry_run
        self.swap_lr = swap_lr
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.direction = "STOP"
        self.last_udp_command = None
        self.last_udp_at = None
        self.pending_stops = deque()
        self.last_cmd_at = None
        self.ttl_s = 0.5
        self.watchdog_stopped = True
        self.watchdog_fired = asyncio.Event()
        self.recovery_requires_zero = False
        self.vx = self.vy = 0.0
        self.seq = 0
        self._last_emergency_at = None
        # Video: the test pattern, the rover's camera (a device number or a
        # stream URL), or none. Either way it passes through the freeze gate.
        self.camera = RobotSim(video="test", fps=10) if video == "test" else None
        self.feed = CameraFeed(parse_source(video)) if video not in ("test", "none") else None
        self.has_video = video != "none"
        # The held frame goes out at the live rate, so nothing on the display
        # (not even its video fps) shows the freeze.
        self.gate = FreezeGate(settle_s=freeze_settle, enabled=not no_freeze, resend_s=0.1)
        self._feed_seq = 0
        self._next_test_frame = 0.0

    def _send_udp(self, command: str) -> None:
        if self.dry_run:
            print(f"UDP {self.target[0]}:{self.target[1]} {command}", flush=True)
        else:
            self.socket.sendto(command.encode("ascii"), self.target)
        self.last_udp_command = command
        self.last_udp_at = time.monotonic()

    def _stop_burst(self, now: float) -> None:
        """Send the first STOP now; schedule two more without queuing motion."""
        self.direction = "STOP"
        self.pending_stops.clear()
        self._send_udp("STOP")
        self.pending_stops.extend((now + 0.02, now + 0.04))

    def emergency_stop(self) -> None:
        """Synchronous best-effort exit path, including cancellation and Ctrl+C."""
        self.direction = "STOP"
        self.watchdog_stopped = True
        self.pending_stops.clear()
        sent = 0
        for index in range(3):
            if index:
                time.sleep(0.02)
            try:
                self._send_udp("STOP")
                sent += 1
            except OSError as exc:
                print(f"UGV STOP send failed: {exc}", flush=True)
        self._last_emergency_at = time.monotonic() if sent == 3 else None

    def ensure_emergency_stop(self) -> None:
        if (self.direction != "STOP" or self._last_emergency_at is None
                or time.monotonic() - self._last_emergency_at > 0.1):
            self.emergency_stop()

    def on_command(self, message: dict) -> None:
        # A packet already buffered by the dead hub may arrive just after
        # the watchdog STOP. Only a new WebSocket session can unlock motion.
        if self.watchdog_fired.is_set():
            return
        vx, vy = message.get("vx"), message.get("vy")
        if (not isinstance(vx, (int, float)) or isinstance(vx, bool)
                or not isinstance(vy, (int, float)) or isinstance(vy, bool)
                or not math.isfinite(vx) or not math.isfinite(vy)):
            return
        new_direction = direction_for(float(vx), float(vy))
        if self.swap_lr:
            new_direction = SWAPPED.get(new_direction, new_direction)
        # If the old socket delivered buffered movement after a freeze, it
        # must not unlock the rover. The next session needs an explicit zero
        # command before any movement can resume.
        if self.recovery_requires_zero:
            if new_direction != "STOP":
                return
            self.recovery_requires_zero = False
        now = time.monotonic()
        ttl = message.get("ttl_ms", 500)
        if isinstance(ttl, (int, float)) and math.isfinite(ttl):
            self.ttl_s = min(0.5, max(0.0, float(ttl) / 1000))
        else:
            self.ttl_s = 0.5
        self.last_cmd_at = now
        self.watchdog_stopped = False
        self.vx, self.vy = float(vx), float(vy)
        self.seq = message.get("seq", self.seq)
        if new_direction == self.direction:
            return
        if new_direction == "STOP":
            self._stop_burst(now)
        else:
            # A fresh direction supersedes pending STOP duplicates; no old
            # packet can be sent after this one.
            self.pending_stops.clear()
            self.direction = new_direction
            self._send_udp(new_direction)

    async def _udp_loop(self):
        while True:
            now = time.monotonic()
            if (not self.watchdog_stopped and self.last_cmd_at is not None
                    and now - self.last_cmd_at >= self.ttl_s):
                self.watchdog_stopped = True
                self.recovery_requires_zero = True
                # A synchronous burst guarantees all three packets before
                # the old socket can deliver any buffered movement command.
                self.emergency_stop()
                self.watchdog_fired.set()
            if self.pending_stops and now >= self.pending_stops[0]:
                self.pending_stops.popleft()
                self._send_udp("STOP")
                if self.pending_stops:
                    self.pending_stops[0] = max(self.pending_stops[0],
                                                time.monotonic() + 0.02)
            interval = 1.0 if self.direction == "STOP" else self.repeat_s
            if (not self.pending_stops and self.last_udp_at is not None
                    and now - self.last_udp_at >= interval):
                self._send_udp(self.direction)
            await asyncio.sleep(0.005)

    async def _receive(self, ws, send_lock):
        async for raw in ws:
            if not isinstance(raw, str):
                continue
            try:
                message = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(message, dict):
                continue
            if message.get("type") == "cmd":
                self.on_command(message)
            elif message.get("type") == "ping":
                async with send_lock:
                    await ws.send(json.dumps({"type": "pong", "t_hub": message.get("t_hub")}))

    def _video_frame(self, now):
        """The JPEG to send now, or None: the newest frame, unless the rover is
        driving or has only just stopped, when the gate holds the last good one."""
        frame = arrived = None
        if self.feed is not None:
            seq, jpeg, stamp = self.feed.latest()
            if seq != self._feed_seq and jpeg is not None:
                self._feed_seq, frame, arrived = seq, jpeg, stamp
        elif self.camera is not None and now >= self._next_test_frame:
            self.camera.vx = 0.0 if self.direction == "STOP" else self.vx
            self.camera.vy = 0.0 if self.direction == "STOP" else self.vy
            self.camera.seq = self.seq
            self.camera.watchdog_stopped = self.watchdog_stopped
            frame, arrived = self.camera.get_frame(), now
            self._next_test_frame = now + 0.1
        return self.gate.step(now, self.direction != "STOP", frame, arrived)

    async def _report(self, ws, send_lock):
        next_telemetry = time.monotonic()
        while True:
            now = time.monotonic()
            if now >= next_telemetry:
                message = {"type": "telemetry", "vx": self.vx, "vy": self.vy,
                           "watchdog_stopped": self.watchdog_stopped,
                           "recovery_requires_zero": self.recovery_requires_zero,
                           "last_udp_command": self.last_udp_command,
                           "battery_v": None,
                           "video_frozen": self.has_video and self.gate.frozen(now)}
                async with send_lock:
                    await ws.send(json.dumps(message))
                next_telemetry = now + 0.2
            if self.has_video:
                frame = self._video_frame(now)
                if frame is not None:
                    async with send_lock:
                        await ws.send(frame)
            await asyncio.sleep(0.01)

    async def session(self, ws, udp_task):
        # Each new hub connection must receive a fresh command before motion.
        self.last_cmd_at = None
        self.watchdog_stopped = True
        self.watchdog_fired.clear()
        send_lock = asyncio.Lock()
        await ws.send(json.dumps({"type": "hello", "client": "robot", "name": "ugv",
                                  "video": {"w": 640, "h": 480,
                                            "fps": 10 if self.has_video else 0}}))
        receiver = asyncio.create_task(self._receive(ws, send_lock))
        reporter = asyncio.create_task(self._report(ws, send_lock))
        watchdog = asyncio.create_task(self.watchdog_fired.wait())
        try:
            done, _ = await asyncio.wait((receiver, reporter, watchdog, udp_task),
                                         return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
            if watchdog in done:
                print("Hub command watchdog fired; reconnecting to require fresh commands.",
                      flush=True)
        finally:
            receiver.cancel()
            reporter.cancel()
            watchdog.cancel()
            self.recovery_requires_zero = True
            # Guarantee the STOP burst before any await can be cancelled.
            self.ensure_emergency_stop()
            await asyncio.gather(receiver, reporter, watchdog, return_exceptions=True)

    async def run(self):
        print(f"UGV UDP target: {self.target[0]}:{self.target[1]}", flush=True)
        self.emergency_stop()
        if self.feed is not None:
            self.feed.start()
        udp_task = asyncio.create_task(self._udp_loop())
        delay = 0.5
        try:
            while True:
                if udp_task.done():
                    udp_task.result()
                try:
                    async with connect(self.hub, max_size=None, open_timeout=5) as ws:
                        print(f"Connected to hub: {self.hub}", flush=True)
                        delay = 0.5
                        await self.session(ws, udp_task)
                        if ws.close_code == 4001:
                            print("Replaced as hub robot; exiting.", flush=True)
                            return
                except ConnectionClosed as exc:
                    if exc.rcvd is not None and exc.rcvd.code == 4001:
                        print("Replaced as hub robot; exiting.", flush=True)
                        return
                    print(f"Hub link lost: {exc}; retrying in {delay:.1f}s", flush=True)
                except OSError as exc:
                    if udp_task.done():
                        udp_task.result()
                    print(f"Hub connection failed: {exc}; retrying in {delay:.1f}s", flush=True)
                await asyncio.sleep(delay)
                delay = min(10.0, delay * 2)
        finally:
            udp_task.cancel()
            self.ensure_emergency_stop()
            with suppress(asyncio.CancelledError, Exception):
                await udp_task
            self.socket.close()
            if self.feed is not None:
                self.feed.stop()
