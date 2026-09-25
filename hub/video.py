"""Newest-frame JPEG relay: one frame slot, no per-viewer queues."""

import asyncio
import time
from collections import deque


# A frame older than this is never sent: a viewer joining after the robot
# has gone must not get its last picture, which would look like a live feed.
MAX_AGE_S = 1.0


class VideoRelay:
    def __init__(self):
        self.frame = None
        self.frame_t = 0.0
        self.sequence = 0
        self.changed = asyncio.Condition()
        self.arrivals = deque()
        self.viewers = 0

    async def publish(self, frame):
        now = time.monotonic()
        async with self.changed:
            self.frame = frame
            self.frame_t = now
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
                    last, frame, frame_t = self.sequence, self.frame, self.frame_t
                if time.monotonic() - frame_t > MAX_AGE_S:
                    continue
                await websocket.send_bytes(frame)
        finally:
            self.viewers -= 1
