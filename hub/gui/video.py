"""Video for the desktop GUI: newest-frame JPEG decode off the render thread.

The network thread calls `push()` with each JPEG. A decoder thread turns
only the newest into an RGB array (older undecoded frames are dropped, never
queued), and the render loop picks it up with `latest()` and uploads it to a
GL texture only when `seq` changed. cv2 releases the GIL while decoding, so
the render thread keeps running.
"""
import threading

import cv2
import numpy as np


class VideoDecoder:
    def __init__(self):
        self._lock = threading.Lock()
        self._jpeg = None
        self._wake = threading.Event()
        self._frame = None
        self.seq = 0            # frames decoded
        self.received = 0
        self.dropped = 0        # replaced before being decoded
        self.errors = 0
        self._stop = False
        self.thread = threading.Thread(target=self._run, name="video-decode", daemon=True)

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self._stop = True
        self._wake.set()

    def push(self, jpeg):
        with self._lock:
            self.received += 1
            if self._jpeg is not None:
                self.dropped += 1
            self._jpeg = jpeg
        self._wake.set()

    def latest(self):
        """(seq, frame): frame is HxWx3 uint8 RGB, row 0 at the top, or None."""
        with self._lock:
            return self.seq, self._frame

    def _run(self):
        while not self._stop:
            self._wake.wait()
            self._wake.clear()
            with self._lock:
                jpeg, self._jpeg = self._jpeg, None
            if jpeg is None:
                continue
            bgr = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
            if bgr is None:
                self.errors += 1
                continue
            rgb = np.ascontiguousarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
            with self._lock:
                self._frame = rgb
                self.seq += 1
