"""The rover's camera for the bridge: a threaded reader and the motion freeze.

The rover's motors and camera share one battery. When the motors start, the
supply sags and the camera browns out (a "Signal Lost" screen or a stalled
stream). `FreezeGate` hides that: while the bridge is driving, and for
`settle_s` after it stops, the display keeps the last frame taken before the
motors started. Live frames resume once the camera has had time to recover.
"""

import threading
import time

import cv2


def parse_source(text):
    """'1' -> capture device 1 (a webcam or USB video receiver).
    Anything else is a URL or file OpenCV opens, e.g. an MJPEG stream
    'http://NeuroMech.local:8000/stream.mjpg' or 'rtsp://...'."""
    return int(text) if text.isdigit() else text


class CameraFeed:
    """Reads a video source in a thread and keeps only the newest frame, as JPEG.

    A dead or stalled stream (the camera browning out, WiFi) is reopened
    every second; the reader never blocks the bridge's event loop. Frames are
    stamped with their arrival time so the freeze can tell which were taken
    before the motors started.
    """

    def __init__(self, source, width=640, quality=70):
        self.source = source
        self.width, self.quality = width, quality
        self.lock = threading.Lock()
        self.seq, self.jpeg, self.arrived = 0, None, None
        self.stopping = threading.Event()
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self._run, name="rover-camera", daemon=True)
        self.thread.start()
        return self

    def stop(self):
        self.stopping.set()
        if self.thread is not None:
            self.thread.join(timeout=3)

    def latest(self):
        """(seq, jpeg bytes or None, arrival time.monotonic() or None)"""
        with self.lock:
            return self.seq, self.jpeg, self.arrived

    def _open(self):
        if isinstance(self.source, int):
            capture = cv2.VideoCapture(self.source)
        else:
            # Without timeouts, a stream that stops mid-frame blocks read()
            # for about 30 s, and the display would show nothing new for that long.
            capture = cv2.VideoCapture(self.source, cv2.CAP_FFMPEG,
                                       [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 3000,
                                        cv2.CAP_PROP_READ_TIMEOUT_MSEC, 2000])
        if capture.isOpened():
            return capture
        capture.release()
        return None

    def _run(self):
        capture, waiting = None, False
        while not self.stopping.is_set():
            if capture is None:
                capture = self._open()
                if capture is None:
                    if not waiting:
                        print(f"Rover camera: waiting for {self.source!r}", flush=True)
                        waiting = True
                    self.stopping.wait(1.0)
                    continue
                print(f"Rover camera: streaming from {self.source!r}", flush=True)
                waiting = False
            ok, image = capture.read()
            if not ok or image is None:
                # A failed read (end of stream, or 2 s with no data) leaves the
                # capture dead: reopen rather than retry it.
                print("Rover camera: stream lost; reopening", flush=True)
                capture.release()
                capture = None
                self.stopping.wait(0.1)
                continue
            h, w = image.shape[:2]
            if w > self.width:
                image = cv2.resize(image, (self.width, round(h * self.width / w)),
                                   interpolation=cv2.INTER_AREA)
            ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, self.quality])
            if ok:
                with self.lock:
                    self.seq += 1
                    self.jpeg = encoded.tobytes()
                    self.arrived = time.monotonic()
        if capture is not None:
            capture.release()


class FreezeGate:
    """Decides which frame goes to the hub, given whether the rover is driving.

    A frame is good if it arrived before the current drive started, or at
    least `settle_s` after the last one ended. Bad frames are dropped. While
    frozen, the last good frame is re-sent every `resend_s`, so a viewer that
    joins mid-drive still gets a picture (the hub never relays a frame older
    than 1 s).
    """

    def __init__(self, settle_s=1.0, enabled=True, resend_s=0.5):
        self.settle_s, self.enabled, self.resend_s = settle_s, enabled, resend_s
        self.moving = False
        self.moved_at = None
        self.stopped_at = float("-inf")
        self.held = None
        self.sent_at = float("-inf")

    def _track(self, moving, now):
        if moving and not self.moving:
            self.moved_at = now
        elif self.moving and not moving:
            self.stopped_at = now
        self.moving = moving

    def frozen(self, now):
        return self.enabled and (self.moving or now < self.stopped_at + self.settle_s)

    def _good(self, arrived):
        if not self.enabled:
            return True
        if self.moving:
            return arrived < self.moved_at
        return arrived >= self.stopped_at + self.settle_s

    def step(self, now, moving, frame=None, arrived=None):
        """Call often (every ~10 ms) with the drive state and any new frame.
        Returns the JPEG to send now, or None."""
        self._track(moving, now)
        if frame is not None and self._good(arrived):
            self.held, self.sent_at = frame, now
            return frame
        if self.frozen(now) and self.held is not None and now - self.sent_at >= self.resend_s:
            self.sent_at = now
            return self.held
        return None
