"""Desktop operator display: full-screen robot video with four SSVEP circles.

Render loop, once per vsync:
  1. t = predicted time of the coming flip (win.getFutureFlipTime), so the
     brightness shown is right for when it is actually on screen, and a late
     frame can't shift the phase (design rule 1: never a frame counter).
  2. If the decoder thread has a newer video frame, upload it to the texture
     (about 20 times a second, ~1 ms). JPEG decoding never runs here.
  3. Draw the video, the circles (raw GL: a dark ring, then the flicker disc),
     the static HUD, then flip.
The hub links and the JPEG decoder run in their own threads (net.py,
video.py); this thread only reads their newest results.
"""
import ctypes
import math
import time

import numpy as np

from .logic import (TARGETS, ArmHold, DriveKeys, FrameLog, FrameStats, Layout,
                    OverrideSender, levels)
from .net import HubClient
from .video import VideoDecoder

RING_SCALE = 1.08       # dark ring around each disc, relative to its radius
RING_GREY = 0.08


def _circle_fan(n=128):
    """Unit-circle triangle fan (centre + n+1 rim points) as a ctypes float array."""
    pts = [0.0, 0.0]
    for i in range(n + 1):
        a = 2 * math.pi * i / n
        pts += [math.cos(a), math.sin(a)]
    return (ctypes.c_float * len(pts))(*pts), n + 2


class VideoTexture:
    """One GL texture, re-uploaded only when a new decoded frame arrives."""

    def __init__(self, GL):
        self.GL = GL
        self.tex = GL.GLuint()
        GL.glGenTextures(1, ctypes.byref(self.tex))
        self.size = None

    def upload(self, rgb):
        GL = self.GL
        h, w = rgb.shape[:2]
        # psychopy leaves other texture units active (masks use unit 1).
        GL.glActiveTexture(GL.GL_TEXTURE0)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.tex)
        GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
        ptr = rgb.ctypes.data_as(ctypes.POINTER(ctypes.c_ubyte))
        if self.size != (w, h):
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
            GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGB, w, h, 0, GL.GL_RGB, GL.GL_UNSIGNED_BYTE, ptr)
            self.size = (w, h)
        else:
            GL.glTexSubImage2D(GL.GL_TEXTURE_2D, 0, 0, 0, w, h, GL.GL_RGB, GL.GL_UNSIGNED_BYTE, ptr)
        GL.glBindTexture(GL.GL_TEXTURE_2D, 0)

    def draw(self, vw, vh):
        """Quad centred at the origin in pix units; image row 0 at the top."""
        GL = self.GL
        x, y = vw / 2, vh / 2
        GL.glActiveTexture(GL.GL_TEXTURE0)
        GL.glEnable(GL.GL_TEXTURE_2D)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.tex)
        GL.glColor4f(1, 1, 1, 1)
        GL.glBegin(GL.GL_QUADS)
        GL.glTexCoord2f(0, 0); GL.glVertex2f(-x, y)
        GL.glTexCoord2f(1, 0); GL.glVertex2f(x, y)
        GL.glTexCoord2f(1, 1); GL.glVertex2f(x, -y)
        GL.glTexCoord2f(0, 1); GL.glVertex2f(-x, -y)
        GL.glEnd()
        GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
        GL.glDisable(GL.GL_TEXTURE_2D)


class App:
    def __init__(self, args):
        self.args = args
        self.quit = None            # None | "q" | "close" | "duration" | "interrupt"
        self.hidden = False

    # ------------------------------------------------------------------ setup

    def _open_window(self):
        from psychopy import logging as plog, visual
        import pyglet

        plog.console.setLevel(plog.WARNING)
        a = self.args
        try:
            screens = pyglet.canvas.get_display().get_screens()
            for i, s in enumerate(screens):
                print("  screen %d: %dx%d at (%d, %d)%s" % (i, s.width, s.height, s.x, s.y,
                                                          "  <- using" if i == a.screen else ""))
        except Exception:
            pass
        kw = dict(screen=a.screen, units="pix", color=[-1, -1, -1], waitBlanking=True,
                  allowGUI=a.windowed, fullscr=not a.windowed, winType="pyglet")
        if a.windowed:
            kw["size"] = a.win_size
        self.win = win = visual.Window(**kw)
        win.recordFrameIntervals = False
        print("  window: %dx%d px, %s" % (win.size[0], win.size[1],
                                         "windowed" if a.windowed else "full screen"))
        refresh = win.getActualFrameRate(nIdentical=20, nMaxFrames=360, nWarmUpFrames=30, threshold=1)
        if refresh is None:
            refresh = 60.0
            print("  ! could not measure the refresh rate, assuming 60 Hz")
        self.refresh = refresh
        win.monitorFramePeriod = 1.0 / refresh
        print("  refresh (measured by psychopy): %.2f Hz" % refresh)
        if refresh < 100:
            print("  ! below 100 Hz: flicker above %.0f Hz can't be shown well. On this laptop use "
                  "the built-in 120 Hz panel (--screen), and set python.exe to High performance "
                  "in Windows Graphics settings." % (refresh / 2))

    def _install_keys(self):
        from pyglet.window import key
        from pyglet.event import EVENT_HANDLED

        drive = {key.UP: "up", key.W: "up", key.DOWN: "down", key.S: "down",
                 key.LEFT: "left", key.A: "left", key.RIGHT: "right", key.D: "right"}
        enter = (key.RETURN, key.ENTER)

        def on_key_press(sym, mods):
            now = time.monotonic()
            if sym in (key.SPACE, key.ESCAPE):
                self.stop_robot("key")
            elif sym in enter:
                self.armhold.press(now)
            elif sym in drive:
                self.drive.press(sym, drive[sym])
            elif sym == key.Q:
                self.quit = "q"
            elif sym == key.F:
                self.hud.show_timing = not self.hud.show_timing
            return EVENT_HANDLED     # keep psychopy's key buffer from growing

        def on_key_release(sym, mods):
            if sym in enter:
                self.armhold.release()
            elif sym in drive:
                self.drive.release(sym)
            return EVENT_HANDLED

        def on_hide():
            # Minimised: the operator can't see the targets any more.
            self.hidden = True
            self.stop_robot("minimised")

        def on_show():
            self.hidden = False
            self.t_prev = None

        def on_deactivate():
            # Key releases won't reach us while unfocused: drop held keys.
            self.drive.clear()
            self.armhold.release()

        def on_close():
            self.quit = "close"
            return EVENT_HANDLED

        self.win.winHandle.push_handlers(on_key_press=on_key_press, on_key_release=on_key_release,
                                         on_hide=on_hide, on_show=on_show,
                                         on_deactivate=on_deactivate, on_close=on_close)
        self._key = key

    def stop_robot(self, why):
        self.drive.clear()
        self.armhold.release()
        sent = self.hub.send_phone({"type": "arm", "armed": False})
        print("  STOP (%s)%s" % (why, "" if sent else " - hub not connected"))

    # ------------------------------------------------------------------ run

    def run(self):
        from psychopy import event
        from pyglet import gl as GL
        from .hud import Hud

        a = self.args
        self._open_window()
        win = self.win
        W, H = win.size
        self.layout = lay = Layout(W, H, size=a.size)
        self.hud = hud = Hud(win, lay)
        self.armhold = ArmHold(1.0)
        self.drive = DriveKeys()
        override = OverrideSender(0.2)
        self.decoder = dec = VideoDecoder().start()
        self.hub = hub = HubClient(a.hub, on_video=None if a.no_video else dec.push,
                                   hello_screen={"w": int(W), "h": int(H), "dpr": 1,
                                                 "refresh_hz": round(self.refresh, 2)}).start()
        self._install_keys()
        script = Script(a.script, self) if a.script else None
        log = FrameLog(a.log_frames) if a.log_frames else None
        stats = FrameStats(1.0 / self.refresh)
        vtex = None if a.no_video else VideoTexture(GL)
        fan, fan_n = _circle_fan()
        lv = np.empty(4)
        r = lay.radius
        centres = [lay.centres[t] for t in TARGETS]
        last_seq, vsize = 0, None
        video_fps, v_seq0 = 0.0, 0
        summary = None
        t_start = time.monotonic()
        win_t0 = None
        self.t_prev = None
        next_text = 0.0
        frame = 0
        print("  hub: ws://%s   keys: Space/Esc STOP, hold Enter ARM, arrows/WASD drive, F timing, Q quit"
              % a.hub)
        try:
            while self.quit is None:
                now = time.monotonic()
                # ---- 1. flicker levels for the coming flip
                t_pred = win.getFutureFlipTime()
                freqs = hub.freqs
                levels(freqs, t_pred, lv)

                # ---- 2. newest video frame -> texture (only when it changed)
                if vtex is not None:
                    seq, img = dec.latest()
                    if seq != last_seq and img is not None:
                        vtex.upload(img)
                        last_seq = seq
                        vsize = lay.video_size(img.shape[1], img.shape[0])

                # ---- 3. draw
                GL.glPushMatrix()
                win.setScale("pix")
                if vsize is not None:
                    vtex.draw(*vsize)
                # Plain coloured fill: pyglet labels leave texturing enabled and
                # psychopy may leave a shader bound, either of which turns the
                # discs black (seen with no video, when nothing else reset it).
                GL.glUseProgram(0)
                GL.glActiveTexture(GL.GL_TEXTURE0)
                GL.glDisable(GL.GL_TEXTURE_2D)
                GL.glEnableClientState(GL.GL_VERTEX_ARRAY)
                GL.glVertexPointer(2, GL.GL_FLOAT, 0, fan)
                for i in range(4):
                    cx, cy = centres[i]
                    GL.glPushMatrix()
                    GL.glTranslatef(cx, cy, 0)
                    GL.glScalef(r * RING_SCALE, r * RING_SCALE, 1)
                    GL.glColor4f(RING_GREY, RING_GREY, RING_GREY, 1)
                    GL.glDrawArrays(GL.GL_TRIANGLE_FAN, 0, fan_n)
                    GL.glScalef(1 / RING_SCALE, 1 / RING_SCALE, 1)
                    g = lv[i]
                    GL.glColor4f(g, g, g, 1)
                    GL.glDrawArrays(GL.GL_TRIANGLE_FAN, 0, fan_n)
                    GL.glPopMatrix()
                GL.glDisableClientState(GL.GL_VERTEX_ARRAY)
                GL.glPopMatrix()

                s = hub.state
                hud.connected = hub.open["phone"]
                if s:
                    hud.set_arm(bool(s.get("armed")), s.get("disarm_reason"))
                    hud.winner = s.get("winner")
                    c = s.get("command") or {}
                    hud.set_arrow(c.get("direction"), c.get("source"))
                else:
                    hud.set_arm(False, "phone_lost" if not hud.connected else None)
                    hud.winner = None
                    hud.set_arrow(None, None)
                hud.arm_progress = self.armhold.progress(now)
                hud.draw()

                t_flip = win.flip()
                frame += 1

                # ---- after the flip: bookkeeping for the next frame
                if log is not None:
                    log.add(frame, t_pred, t_flip, lv, freqs)
                if self.t_prev is not None and not self.hidden:
                    stats.add(t_flip - self.t_prev)
                self.t_prev = t_flip
                if win_t0 is None:
                    win_t0 = t_flip
                elif t_flip - win_t0 >= 1.0:
                    summary = stats.summary(t_flip - win_t0)
                    win_t0 = t_flip
                    hub.send_phone({"type": "frame_stats", **summary, "rtt_ms": hub.rtt_ms})
                    video_fps, v_seq0 = dec.seq - v_seq0, dec.seq
                    event.clearEvents()

                if self.armhold.update(now):
                    sent = hub.send_phone({"type": "arm", "armed": True})
                    print("  ARM%s" % ("" if sent else " - hub not connected"))
                msg = override.tick(now, self.drive.current())
                if msg is not None:
                    hub.send_dashboard(msg)

                if now >= next_text:
                    next_text = now + 0.5
                    hud.set_text(hud.status, status_line(hub, s, summary, video_fps))
                    if hud.show_timing:
                        hud.set_text(hud.timing, timing_line(stats, summary, dec, self.refresh))

                if script is not None:
                    script.step(now - t_start)
                if a.duration and now - t_start >= a.duration:
                    self.quit = "duration"
                if self.hidden:
                    time.sleep(0.01)   # flips don't block while minimised
        except KeyboardInterrupt:
            self.quit = "interrupt"
        finally:
            if self.quit == "q":
                self.hub.send_phone({"type": "arm", "armed": False})
                self.hub.flush()
            hub.stop()
            dec.stop()
            try:
                win.close()
            except Exception:
                pass
            elapsed = time.monotonic() - t_start
            print("  quit (%s) after %.1f s: %d frames, %.1f fps, late (>1.5 frames) %d = %.2f%%, "
                  "max interval %.1f ms; video decoded %d, dropped %d"
                  % (self.quit, elapsed, frame, frame / max(elapsed, 1e-9), stats.late,
                     stats.late_pct, stats.max_ms, dec.seq, dec.dropped))
            if log is not None:
                print("  frame log: %d rows -> %s" % (log.save(), log.path))


def status_line(hub, s, summary, video_fps):
    parts = ["hub " + ("ok" if hub.open["phone"] else "DOWN")
             + (" %d ms" % hub.rtt_ms if hub.rtt_ms is not None else "")]
    eeg = (s or {}).get("eeg") or {}
    parts.append("EEG " + ("-" if not eeg else ("ok" if eeg.get("ok") else "STALLED")))
    rob = (s or {}).get("robot") or {}
    parts.append("robot " + ((rob.get("name") or "ok") if rob.get("connected") else "-"))
    if summary:
        parts.append("%.0f fps  p95 %.1f ms  dropped %d" % (summary["fps"], summary["p95_ms"], summary["dropped"]))
    parts.append("video %d fps" % video_fps)
    return "   |   ".join(parts)


def timing_line(stats, summary, dec, refresh):
    fps = summary["fps"] if summary else 0
    return ("refresh %.2f Hz   %.1f fps   late %d/%d (%.2f%%)   max %.1f ms\n"
            "video decoded %d  dropped %d" % (refresh, fps, stats.late, stats.total, stats.late_pct,
                                              stats.max_ms, dec.seq, dec.dropped))


class Script:
    """--script "2:enter_down,3.3:enter_up,5:up_down,6:up_up,8:space,9:shot,10:quit"

    Feeds synthetic key events into the window at the given times (seconds
    from start), so the key handling can be exercised without a person.
    """

    NAMES = {"enter": "RETURN", "space": "SPACE", "esc": "ESCAPE", "up": "UP", "down": "DOWN",
             "left": "LEFT", "right": "RIGHT", "w": "W", "a": "A", "s": "S", "d": "D",
             "f": "F", "q": "Q"}

    def __init__(self, spec, app):
        self.app = app
        self.shots = 0
        self.events = []
        for item in spec.split(","):
            t, action = item.split(":")
            self.events.append((float(t), action.strip()))
        self.events.sort()

    def step(self, t):
        from pyglet.window import key
        wh = self.app.win.winHandle
        while self.events and self.events[0][0] <= t:
            _, action = self.events.pop(0)
            if action == "quit":
                self.app.quit = "q"
                continue
            if action == "shot":
                win = self.app.win
                self.shots += 1
                path = self.app.args.screenshot or "gui_screenshot.png"
                if self.shots > 1:
                    stem, dot, ext = path.rpartition(".")
                    path = "%s_%d.%s" % (stem, self.shots, ext) if dot else "%s_%d" % (path, self.shots)
                win.getMovieFrame(buffer="front")
                win.saveMovieFrames(path)
                continue
            if action in ("hide", "show", "close"):
                wh.dispatch_event("on_" + action)
                continue
            name, _, phase = action.partition("_")
            sym = getattr(key, self.NAMES[name])
            if phase in ("", "down"):
                wh.dispatch_event("on_key_press", sym, 0)
            if phase in ("", "up"):
                wh.dispatch_event("on_key_release", sym, 0)
