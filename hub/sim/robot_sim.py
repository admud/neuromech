"""Headless /ws/robot client and Raspberry Pi protocol template."""

import argparse
import asyncio
import json
import time
from contextlib import suppress
from datetime import datetime

import cv2
import numpy as np
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed


class RobotSim:
    def __init__(self, hub="ws://127.0.0.1:8765/ws/robot", video="test",
                 camera=0, fps=20, max_speed=0.5):
        self.hub, self.video, self.camera, self.fps = hub, video, camera, fps
        self.max_speed = max_speed
        self.x = self.y = 0.0
        self.vx = self.vy = 0.0
        self.seq = 0
        self.ttl_s = 0.5
        self.last_cmd = None
        self.watchdog_stopped = True
        self.capture = None

    def drive(self, vx, vy):
        """Apply normalised robot-frame velocity; replace on the Pi."""
        self.vx = max(-1.0, min(1.0, float(vx)))
        self.vy = max(-1.0, min(1.0, float(vy)))

    def get_frame(self):
        """Return a JPEG frame; replace camera capture on the Pi."""
        if self.video == "webcam" and self.capture is not None:
            ok, image = self.capture.read()
            if not ok:
                image = np.zeros((480, 640, 3), np.uint8)
            else:
                image = cv2.resize(image, (640, 480))
        else:
            image = np.full((480, 640, 3), (29, 31, 37), np.uint8)
            cv2.rectangle(image, (24, 24), (616, 456), (75, 98, 112), 2)
            cv2.line(image, (320, 205), (320, 275), (80, 180, 220), 1)
            cv2.line(image, (290, 240), (350, 240), (80, 180, 220), 1)
            cv2.putText(image, "NEUROMECH TEST CAMERA", (38, 68),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.75, (180, 220, 230), 2)
        lines = [datetime.now().strftime("%H:%M:%S.%f")[:-3],
                 f"vx {self.vx:+.2f}  vy {self.vy:+.2f}  seq {self.seq}",
                 f"watchdog {'STOPPED' if self.watchdog_stopped else 'OK'}  x {self.x:+.2f}  y {self.y:+.2f}"]
        for index, line in enumerate(lines):
            cv2.putText(image, line, (34, 338 + index * 36),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.72, (80, 230, 180), 2)
        ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 70])
        if not ok:
            raise RuntimeError("JPEG encode failed")
        return encoded.tobytes()

    def _check_watchdog(self, now):
        if self.last_cmd is None or now - self.last_cmd > self.ttl_s:
            if not self.watchdog_stopped:
                self.drive(0, 0)
            self.watchdog_stopped = True

    async def _watchdog(self):
        # Its own task, so a send blocked by a stalled hub or a congested
        # link can never delay the motor stop.
        while True:
            self._check_watchdog(time.monotonic())
            await asyncio.sleep(0.02)

    def _advance(self, now, previous):
        self._check_watchdog(now)
        dt = min(now - previous, 0.25)
        self.x += self.vx * self.max_speed * dt
        self.y += self.vy * self.max_speed * dt

    async def _receive(self, ws):
        async for raw in ws:
            if not isinstance(raw, str):
                continue
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(msg, dict):
                continue
            if msg.get("type") == "cmd":
                self.seq = msg.get("seq", self.seq)
                self.ttl_s = max(0, float(msg.get("ttl_ms", 500)) / 1000)
                self.last_cmd = time.monotonic()
                self.watchdog_stopped = False
                self.drive(msg.get("vx", 0), msg.get("vy", 0))
            elif msg.get("type") == "ping":
                await ws.send(json.dumps({"type": "pong", "t_hub": msg.get("t_hub")}))

    async def _tick(self, ws):
        previous = time.monotonic()
        next_video = next_telemetry = previous
        while True:
            now = time.monotonic()
            self._advance(now, previous)
            previous = now
            if now >= next_telemetry:
                await ws.send(json.dumps({"type": "telemetry", "vx": self.vx,
                                          "vy": self.vy,
                                          "watchdog_stopped": self.watchdog_stopped,
                                          "battery_v": None, "x": self.x, "y": self.y,
                                          "heading": 0.0, "collision": False}))
                next_telemetry = now + 0.1
            if now >= next_video:
                await ws.send(self.get_frame())
                next_video = now + 1 / self.fps
            await asyncio.sleep(min(0.02, max(0.001, min(next_video, next_telemetry) - time.monotonic())))

    async def session(self, ws):
        self.drive(0, 0)
        self.last_cmd = None
        self.watchdog_stopped = True
        await ws.send(json.dumps({"type": "hello", "client": "robot", "name": "sim",
                                  "video": {"w": 640, "h": 480, "fps": self.fps}}))
        receiver = asyncio.create_task(self._receive(ws))
        ticker = asyncio.create_task(self._tick(ws))
        watchdog = asyncio.create_task(self._watchdog())
        try:
            done, pending = await asyncio.wait((receiver, ticker, watchdog), return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        finally:
            for task in (receiver, ticker, watchdog):
                task.cancel()
                with suppress(asyncio.CancelledError, ConnectionClosed):
                    await task
            self.drive(0, 0)
            self.watchdog_stopped = True

    async def run(self):
        if self.video == "webcam":
            self.capture = cv2.VideoCapture(self.camera)
            if not self.capture.isOpened():
                raise RuntimeError(f"Could not open camera {self.camera}")
        delay = 0.5
        try:
            while True:
                try:
                    async with connect(self.hub, max_size=None) as ws:
                        print(f"Connected to {self.hub}", flush=True)
                        delay = 0.5
                        await self.session(ws)
                except (OSError, ConnectionClosed) as exc:
                    print(f"Robot link lost: {exc}; retrying in {delay:.1f}s", flush=True)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 10)
        finally:
            if self.capture is not None:
                self.capture.release()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Headless NeuroMech robot simulator")
    parser.add_argument("--hub", default="ws://127.0.0.1:8765/ws/robot")
    parser.add_argument("--video", choices=("test", "webcam"), default="test")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--fps", type=float, default=20)
    args = parser.parse_args(argv)
    if args.fps <= 0:
        parser.error("--fps must be positive")
    try:
        asyncio.run(RobotSim(**vars(args)).run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
