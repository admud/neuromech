"""Newest-frame JPEG relay: one frame slot, no per-viewer queues."""

import asyncio
import time
from collections import deque


class VideoRelay:
    def __init__(self):
        self.frame = None
        self.sequence = 0
        self.changed = asyncio.Condition()
        self.arrivals = deque()
        self.viewers = 0

    async def publish(self, frame):
        now = time.monotonic()
        async with self.changed:
            self.frame = frame
            self.sequence += 1
            self.arrivals.append(now)
            self._trim(now)
            self.changed.notify_all()

    def _trim(self, now):
        while self.arrivals and self.arrivals[0] < now - 1.0:
            self.arrivals.popleft()

    def status(self):
        self._trim(time.monotonic())
        return {"in_fps": len(self.arrivals), "viewers": self.viewers}

    async def serve(self, websocket):
        self.viewers += 1
        last = 0
        try:
            while True:
                async with self.changed:
                    await self.changed.wait_for(lambda: self.sequence > last)
                    last, frame = self.sequence, self.frame
                await websocket.send_bytes(frame)
        finally:
            self.viewers -= 1
