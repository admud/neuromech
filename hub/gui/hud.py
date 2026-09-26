"""Static (non-flickering) overlays: arm state, winner ring, command arrow,
status line, DISCONNECTED banner, hold-to-arm bar, timing overlay.

Text is drawn with pyglet Labels, not psychopy TextStims: changing a
TextStim's text re-renders it (~2.7 ms here), which made one frame late
every time the status line changed; a Label update is ~0.6 ms. Setters
still only touch a label when its content changed, and the caller updates
the status line at most twice a second.
"""
import pyglet
from psychopy import visual

from .logic import TARGETS

REASONS = {"startup": "hold Enter to arm", "user": "stopped", "phone_lost": "display link lost",
           "eeg_stall": "EEG stalled", "robot_lost": "robot link lost"}
ARROW_ORI = {"up": 0, "right": 90, "down": 180, "left": 270}
GREEN = [-0.6, 1.0, -0.6]
BLUE = [-0.4, 0.2, 1.0]
KEYS_HELP = "Space/Esc STOP   hold Enter ARM   arrows/WASD drive   F timing   Q quit"


def _rgba(c, a=255):
    """psychopy rgb (-1..1) -> pyglet RGBA 0..255."""
    return tuple(int(round((v + 1) * 127.5)) for v in c) + (a,)


class Text:
    """Minimal stand-in for a TextStim, backed by a pyglet Label."""

    def __init__(self, text="", pos=(0, 0), height=20, color=(1, 1, 1), bold=False,
                 anchor_x="left", anchor_y="baseline", multiline=False, width=None):
        self.label = pyglet.text.Label(text, font_size=height * 0.75, bold=bold, color=_rgba(color),
                                       x=pos[0], y=pos[1], anchor_x=anchor_x, anchor_y=anchor_y,
                                       multiline=multiline, width=width)

    @property
    def text(self):
        return self.label.text

    @text.setter
    def text(self, value):
        self.label.text = value

    @property
    def color(self):
        return self.label.color

    @color.setter
    def color(self, c):
        self.label.color = _rgba(c)

    def draw(self):
        self.label.draw()


class Hud:
    def __init__(self, win, layout):
        self.win = win
        h = layout.h
        w = layout.w
        u = h / 1440.0 * 1.0       # scale text with the window
        pad = 18 * u
        self.layout = layout
        self.armstate = Text("DISARMED", pos=(-w / 2 + pad, h / 2 - pad), anchor_y="top", height=48 * u,
                             bold=True, color=[1, 0.7, -0.6])
        self.reason = Text("", pos=(-w / 2 + pad, h / 2 - pad - 60 * u), anchor_y="top", height=28 * u,
                           color=[1, 0.7, -0.6])
        self.status = Text("", pos=(-w / 2 + pad, -h / 2 + pad), anchor_y="bottom", height=22 * u,
                           color=[0.6, 0.6, 0.6])
        self.help = Text(KEYS_HELP, pos=(w / 2 - pad, -h / 2 + pad), anchor_x="right", anchor_y="bottom",
                         height=20 * u, color=[0.2, 0.2, 0.2])
        # Left column under the arm state, clear of the top circle.
        self.timing = Text("", pos=(-w / 2 + pad, h / 2 - pad - 110 * u), anchor_y="top", height=22 * u,
                           color=[1, 1, 0.2], multiline=True, width=int(w / 2 - layout.radius * 1.3 - pad))
        self.banner = Text("DISCONNECTED from hub - reconnecting", pos=(0, h * 0.12), anchor_x="center",
                           anchor_y="center", height=44 * u, bold=True, color=[1, -0.6, -0.6])
        self.banner_bg = visual.Rect(win, width=w * 0.5, height=80 * u, pos=(0, h * 0.12),
                                     fillColor=[-0.6, -1, -1], lineColor=None, opacity=0.85)
        r = layout.radius
        self.rings = {t: visual.Circle(win, radius=r * 1.16, pos=layout.centres[t], edges=96,
                                       fillColor=None, lineColor=GREEN, lineWidth=max(4, 10 * u))
                      for t in TARGETS}
        s = h * 0.05
        self.arrow = visual.ShapeStim(win, vertices=[(0, s), (-0.8 * s, -0.6 * s), (0.8 * s, -0.6 * s)],
                                      fillColor=GREEN, lineColor=[-1, -1, -1], lineWidth=3 * u,
                                      pos=(0, 0))
        self.armbar_bg = visual.Rect(win, width=w * 0.3, height=16 * u, pos=(0, -h * 0.28),
                                     fillColor=[-0.6, -0.6, -0.6], lineColor=None)
        self.armbar = visual.Rect(win, width=1, height=16 * u, pos=(0, -h * 0.28),
                                  fillColor=GREEN, lineColor=None, anchor="left")
        self.armbar_w = w * 0.3
        # Rasterise every glyph we'll ever show now, not mid-run: a new glyph
        # costs a texture upload, which made the first seconds' frames late.
        warm = "".join(chr(c) for c in range(32, 127))
        for t in (self.armstate, self.reason, self.status, self.help, self.timing, self.banner):
            keep = t.text
            t.text = warm
            t.draw()
            t.text = keep
        self._armed = None
        self._reason = None
        self._arrow = None
        self.show_timing = False
        self.connected = False
        self.winner = None
        self.arm_progress = 0.0

    def set_arm(self, armed, reason):
        if armed != self._armed:
            self._armed = armed
            self.armstate.text = "ARMED" if armed else "DISARMED"
            self.armstate.color = [-0.4, 1, -0.4] if armed else [1, 0.7, -0.6]
        r = None if armed else reason
        if r != self._reason:
            self._reason = r
            self.reason.text = REASONS.get(r, r or "")

    def set_arrow(self, direction, source):
        key = (direction, source) if direction in ARROW_ORI else None
        if key != self._arrow:
            self._arrow = key
            if key:
                self.arrow.ori = ARROW_ORI[direction]
                self.arrow.fillColor = BLUE if source == "override" else GREEN

    @staticmethod
    def set_text(stim, text):
        if stim.text != text:
            stim.text = text

    def draw(self):
        from pyglet import gl as GL
        if self.winner in self.rings:
            self.rings[self.winner].draw()
        if self._arrow:
            self.arrow.draw()
        if self.arm_progress > 0:
            self.armbar_bg.draw()
            self.armbar.width = max(1.0, self.armbar_w * self.arm_progress)
            self.armbar.pos = (-self.armbar_w / 2, self.armbar.pos[1])
            self.armbar.draw()
        if not self.connected:
            self.banner_bg.draw()
        # pyglet labels draw in the current modelview: set psychopy's pix scale.
        GL.glPushMatrix()
        self.win.setScale("pix")
        GL.glActiveTexture(GL.GL_TEXTURE0)   # pyglet's glyph textures use unit 0
        self.armstate.draw()
        if self._reason is not None:
            self.reason.draw()
        self.status.draw()
        self.help.draw()
        if self.show_timing:
            self.timing.draw()
        if not self.connected:
            self.banner.draw()
        GL.glPopMatrix()
