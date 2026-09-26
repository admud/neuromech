"""Browser-free virtual robot: the web sim's arena and physics, rendered on the CPU.

It is a /ws/robot client like robot_sim and the web twin (hello name
"virtual"): it applies `cmd`s with the same watchdog, moves through the arena
in web/twin/worlds/default.json with circle-vs-box collisions that slide
along walls (a port of web/twin/physics.js), and streams a first-person JPEG
view rendered with numpy + OpenCV. No browser and no GPU, so the desktop
GUI keeps the laptop's graphics to itself.

    python -m hub.sim.virtual [--hub ws://127.0.0.1:8765/ws/robot]
                              [--world web/twin/worlds/default.json] [--fps 20] [--minimap]
"""

import argparse
import asyncio
import json
import math
import os
import sys
import threading
import time
from contextlib import suppress
from pathlib import Path

import cv2
import numpy as np
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from .robot_sim import RobotSim

DEFAULT_WORLD = Path(__file__).resolve().parents[2] / "web" / "twin" / "worlds" / "default.json"
# Camera sits at the front of the chassis, as in web/twin/robot_model.js (DIMS.camera.x).
CAMERA_X = 0.135
NEAR = 0.03
CONTACT_EPS = 0.002
# Light direction (towards the sun), roughly the web sim's: high, from behind-right.
LIGHT = np.array([-0.3, -0.45, 0.85]) / np.linalg.norm([-0.3, -0.45, 0.85])


def _hex_bgr(color, default=(153, 144, 138)):
    """'#rrggbb' -> (b, g, r)."""
    try:
        c = color.lstrip("#")
        return (int(c[4:6], 16), int(c[2:4], 16), int(c[0:2], 16))
    except (AttributeError, ValueError, IndexError):
        return default


# --- world ------------------------------------------------------------------

class World:
    """The arena from a world file (schema in plan/protocol.md), as boxes.

    Matches web/twin/world.js: the perimeter is implicit from arena.size
    (height arena.wall_h, thickness arena.wall_t), then the file's walls."""

    def __init__(self, data):
        self.data = data
        self.sx, self.sy = (float(v) for v in data["arena"]["size"])
        wall_h = float(data["arena"].get("wall_h", 0.3))
        wall_t = float(data["arena"].get("wall_t", 0.1))
        sx, sy, t = self.sx, self.sy, wall_t
        grey = "#9aa0a8"
        boxes = [
            {"x": 0, "y": sy / 2 + t / 2, "w": sx + 2 * t, "d": t, "h": wall_h, "color": grey},
            {"x": 0, "y": -sy / 2 - t / 2, "w": sx + 2 * t, "d": t, "h": wall_h, "color": grey},
            {"x": sx / 2 + t / 2, "y": 0, "w": t, "d": sy, "h": wall_h, "color": grey},
            {"x": -sx / 2 - t / 2, "y": 0, "w": t, "d": sy, "h": wall_h, "color": grey},
            *data.get("walls", []),
        ]
        self.boxes = []
        for b in boxes:
            yaw = math.radians(float(b.get("yaw_deg", 0)))
            self.boxes.append({
                "x": float(b["x"]), "y": float(b["y"]), "hw": float(b["w"]) / 2,
                "hd": float(b["d"]) / 2, "h": float(b.get("h", 0.3)),
                "c": math.cos(yaw), "s": math.sin(yaw), "color": _hex_bgr(b.get("color")),
            })
        self.goal = data.get("goal")
        robot = data.get("robot", {})
        self.radius = float(robot.get("radius", 0.15))
        self.max_speed = float(robot.get("max_speed_mps", 0.5))
        self.camera = {"height_m": 0.25, "pitch_deg": -10, "hfov_deg": 70, "w": 640, "h": 480,
                       **robot.get("camera", {})}
        spawn = data.get("spawn", {})
        self.spawn = (float(spawn.get("x", 0)), float(spawn.get("y", 0)), float(spawn.get("heading", 0)))

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as f:
            return cls(json.load(f))


# --- physics (port of web/twin/physics.js) ------------------------------------

def resolve(px, py, r, boxes):
    """Push a circle of radius r at (px, py) out of every box.

    Returns (x, y, hit). Pushing out along the contact normal cancels only
    the into-wall part of the motion, so the robot slides along walls."""
    hit = False
    for _ in range(4):                      # a few passes settle corners
        moved = False
        for b in boxes:
            dx, dy = px - b["x"], py - b["y"]
            lx = b["c"] * dx + b["s"] * dy
            ly = -b["s"] * dx + b["c"] * dy
            qx = max(-b["hw"], min(b["hw"], lx))
            qy = max(-b["hd"], min(b["hd"], ly))
            nx, ny = lx - qx, ly - qy
            dist = math.hypot(nx, ny)
            if dist >= r + CONTACT_EPS:
                continue
            hit = True
            if dist >= r:
                continue                    # touching, not penetrating
            if dist < 1e-9:
                # Centre inside the box: leave by the nearest face.
                ox, oy = b["hw"] - abs(lx), b["hd"] - abs(ly)
                if ox < oy:
                    nx, ny, dist = math.copysign(1, lx), 0.0, -ox
                else:
                    nx, ny, dist = 0.0, math.copysign(1, ly), -oy
            else:
                nx, ny = nx / dist, ny / dist
            push = r - dist
            px += (b["c"] * nx - b["s"] * ny) * push
            py += (b["s"] * nx + b["c"] * ny) * push
            moved = True
        if not moved:
            break
    return px, py, hit


def step(pose, vxm, vym, dt, r, boxes):
    """Advance pose [x, y, heading] by robot-frame velocity (m/s) for dt s.

    Sub-steps keep a fast robot from tunnelling through thin walls. Returns
    True while touching a wall."""
    c, s = math.cos(pose[2]), math.sin(pose[2])
    wx, wy = c * vxm - s * vym, s * vxm + c * vym
    n = max(1, math.ceil(math.hypot(wx, wy) * dt / (r * 0.25)))
    hit = False
    for _ in range(n):
        pose[0], pose[1], h = resolve(pose[0] + wx * dt / n, pose[1] + wy * dt / n, r, boxes)
        hit = hit or h
    return hit


# --- rendering -----------------------------------------------------------------

class Camera:
    """Pinhole camera on the robot: position/pitch from the world file."""

    def __init__(self, cam):
        self.w, self.h = int(cam["w"]), int(cam["h"])
        self.height = float(cam["height_m"])
        self.pitch = math.radians(float(cam["pitch_deg"]))
        self.f = (self.w / 2) / math.tan(math.radians(float(cam["hfov_deg"])) / 2)
        self.cx, self.cy = self.w / 2, self.h / 2

    def basis(self, x, y, heading):
        """Camera origin and (right, up, forward) axes in the world."""
        ch, sh = math.cos(heading), math.sin(heading)
        origin = np.array([x + CAMERA_X * ch, y + CAMERA_X * sh, self.height])
        cp, sp = math.cos(self.pitch), math.sin(self.pitch)
        fwd = np.array([ch * cp, sh * cp, sp])
        right = np.array([sh, -ch, 0.0])
        up = np.cross(right, fwd)
        return origin, np.stack([right, up, fwd])

    def to_cam(self, pts, origin, axes):
        """World points (N, 3) -> camera coords (N, 3): x right, y up, z forward."""
        return (np.asarray(pts, float) - origin) @ axes.T

    def project(self, pc):
        """Camera coords (N, 3) with z > 0 -> pixel coords (N, 2)."""
        return np.stack([self.cx + self.f * pc[:, 0] / pc[:, 2],
                         self.cy - self.f * pc[:, 1] / pc[:, 2]], axis=1)


def clip_near(poly):
    """Clip a camera-space polygon (N, 3) to z >= NEAR (Sutherland-Hodgman)."""
    out = []
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        ain, bin_ = a[2] >= NEAR, b[2] >= NEAR
        if ain:
            out.append(a)
        if ain != bin_:
            t = (NEAR - a[2]) / (b[2] - a[2])
            out.append(a + t * (b - a))
    return np.array(out) if len(out) >= 3 else None


def clip_segment(a, b):
    """Clip a camera-space segment to z >= NEAR. Returns (a, b) or None."""
    if a[2] < NEAR and b[2] < NEAR:
        return None
    if a[2] < NEAR:
        a = a + (NEAR - a[2]) / (b[2] - a[2]) * (b - a)
    elif b[2] < NEAR:
        b = b + (NEAR - b[2]) / (a[2] - b[2]) * (a - b)
    return a, b


SHIFT = 4                                   # sub-pixel bits for cv2 drawing
SCALE = 1 << SHIFT


def _fix(px):
    # Keep far-off points inside int32 range for cv2.
    return np.clip(np.round(px * SCALE), -1e8, 1e8).astype(np.int32)


class Renderer:
    """First-person view of the arena on the CPU: sky gradient, floor with a
    0.5 m grid, goal pad, and boxes as shaded faces in painter's order."""

    GRID = 0.5
    FLOOR = (207, 214, 217)                 # BGR, like the web sim's floor tiles
    OUTSIDE = (71, 63, 58)
    GRID_LINE = (128, 138, 143)

    def __init__(self, world, minimap=False):
        self.world = world
        self.cam = Camera(world.camera)
        self.minimap = minimap
        self._background = self._make_background()
        self._faces = self._make_faces()
        self._grid = self._make_grid()
        self._goal = self._make_goal()
        self._map = self._make_minimap() if minimap else None

    def _make_background(self):
        # Pitch and height are fixed and there's no roll, so the horizon row
        # never moves: the sky and the far ground are one precomputed image.
        h, w = self.cam.h, self.cam.w
        horizon = self.cam.cy - self.cam.f * math.tan(-self.cam.pitch)
        rows = np.arange(h, dtype=float)[:, None]
        top, bottom = np.array([60, 44, 34.0]), np.array([118, 104, 92.0])
        t = np.clip(rows / max(horizon, 1), 0, 1)
        sky = top * (1 - t) + bottom * t
        img = np.where(rows < horizon, sky, np.array(self.OUTSIDE, float))
        return np.repeat(img[:, None, :], w, axis=1).astype(np.uint8).reshape(h, w, 3)

    def _make_faces(self):
        faces = []
        for index, b in enumerate(self.world.boxes):
            # Everything is inside the perimeter, so its faces always go
            # behind the rest; sorting its long faces by centre distance
            # could put a wall over a nearer box.
            layer = 0 if index < 4 else 1
            c, s, hw, hd, hgt = b["c"], b["s"], b["hw"], b["hd"], b["h"]
            corners = []
            for lx, ly in ((-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd)):
                corners.append((b["x"] + c * lx - s * ly, b["y"] + s * lx + c * ly))
            base = np.array(b["color"], float)
            for i in range(4):
                (x0, y0), (x1, y1) = corners[i], corners[(i + 1) % 4]
                quad = np.array([[x0, y0, 0], [x1, y1, 0], [x1, y1, hgt], [x0, y0, hgt]])
                ex, ey = x1 - x0, y1 - y0
                norm = np.array([ey, -ex, 0.0]) / math.hypot(ex, ey)   # outward for CCW corners
                faces.append((quad, norm, self._shade(base, norm), layer))
            top = np.array([[x, y, hgt] for x, y in corners])
            faces.append((top, np.array([0, 0, 1.0]), self._shade(base, np.array([0, 0, 1.0])), layer))
        return faces

    @staticmethod
    def _shade(base, normal):
        k = 0.55 + 0.5 * max(0.0, float(normal @ LIGHT))
        return tuple(int(v) for v in np.clip(base * k, 0, 255))

    def _make_grid(self):
        sx, sy, g = self.world.sx, self.world.sy, self.GRID
        segs = []
        for i in range(int(round(sx / g)) + 1):
            x = -sx / 2 + i * g
            segs.append(((x, -sy / 2, 0), (x, sy / 2, 0)))
        for j in range(int(round(sy / g)) + 1):
            y = -sy / 2 + j * g
            segs.append(((-sx / 2, y, 0), (sx / 2, y, 0)))
        return np.array(segs, float)

    def _make_goal(self):
        g = self.world.goal
        if not g:
            return None
        a = np.linspace(0, 2 * math.pi, 32, endpoint=False)
        return np.stack([g["x"] + g["r"] * np.cos(a), g["y"] + g["r"] * np.sin(a),
                         np.full_like(a, 0.001)], axis=1)

    def _fill(self, img, pc, color, edge=None):
        poly = clip_near(pc)
        if poly is not None:
            pts = [_fix(self.cam.project(poly))]
            cv2.fillPoly(img, pts, color, cv2.LINE_AA, SHIFT)
            if edge is not None:
                cv2.polylines(img, pts, True, edge, 1, cv2.LINE_AA, SHIFT)

    def render(self, x, y, heading):
        """BGR image (h, w, 3) seen from the robot at pose (x, y, heading)."""
        img = self._background.copy()
        origin, axes = self.cam.basis(x, y, heading)
        to_cam = lambda p: self.cam.to_cam(p, origin, axes)   # noqa: E731
        sx, sy = self.world.sx, self.world.sy

        floor = np.array([[-sx / 2, -sy / 2, 0], [sx / 2, -sy / 2, 0],
                          [sx / 2, sy / 2, 0], [-sx / 2, sy / 2, 0]])
        self._fill(img, to_cam(floor), self.FLOOR)

        grid = to_cam(self._grid.reshape(-1, 3)).reshape(-1, 2, 3)
        lines = []
        for a, b in grid:
            seg = clip_segment(a, b)
            if seg is not None:
                lines.append(_fix(self.cam.project(np.array(seg))))
        if lines:
            cv2.polylines(img, lines, False, self.GRID_LINE, 2, cv2.LINE_AA, SHIFT)

        if self._goal is not None:
            self._fill(img, to_cam(self._goal), (107, 184, 47))

        # Boxes: cull faces pointing away, then draw far to near.
        visible = []
        for quad, normal, color, layer in self._faces:
            if normal @ (origin - quad[0]) <= 0:
                continue
            pc = to_cam(quad)
            if (pc[:, 2] < NEAR).all():
                continue
            dist = float(np.linalg.norm(quad.mean(axis=0) - origin))
            visible.append((layer, -dist, pc, color))
        visible.sort(key=lambda v: (v[0], v[1]))
        for _, _, pc, color in visible:
            # Darker outline: two faces of one box can shade alike, and the
            # edge keeps the shape readable.
            self._fill(img, pc, color, tuple(int(c * 0.6) for c in color))

        if self._map is not None:
            self._draw_minimap(img, x, y, heading)
        return img

    # Minimap: top-down, x to the right, y up, like the web sim's top view.
    MAP_W = 150

    def _map_xform(self):
        sx, sy = self.world.sx + 0.2, self.world.sy + 0.2
        k = self.MAP_W / sx
        return k, int(round(sy * k))

    def _to_map(self, x, y):
        k, mh = self._map_xform()
        return (x + (self.world.sx + 0.2) / 2) * k, mh - (y + (self.world.sy + 0.2) / 2) * k

    def _make_minimap(self):
        k, mh = self._map_xform()
        m = np.full((mh, self.MAP_W, 3), (40, 36, 32), np.uint8)
        sx, sy = self.world.sx, self.world.sy
        a, b = self._to_map(-sx / 2, sy / 2), self._to_map(sx / 2, -sy / 2)
        cv2.rectangle(m, (int(a[0]), int(a[1])), (int(b[0]), int(b[1])), (150, 156, 160), -1)
        if self.world.goal:
            g = self.world.goal
            cx, cy = self._to_map(g["x"], g["y"])
            cv2.circle(m, (int(cx), int(cy)), max(2, int(g["r"] * k)), (107, 184, 47), -1, cv2.LINE_AA)
        for bx in self.world.boxes:
            pts = []
            for lx, ly in ((-bx["hw"], -bx["hd"]), (bx["hw"], -bx["hd"]), (bx["hw"], bx["hd"]), (-bx["hw"], bx["hd"])):
                pts.append(self._to_map(bx["x"] + bx["c"] * lx - bx["s"] * ly, bx["y"] + bx["s"] * lx + bx["c"] * ly))
            cv2.fillPoly(m, [_fix(np.array(pts))], bx["color"], cv2.LINE_AA, SHIFT)
        return m

    def _draw_minimap(self, img, x, y, heading):
        m = self._map.copy()
        k, _ = self._map_xform()
        cx, cy = self._to_map(x, y)
        r = max(3, int(self.world.radius * k))
        cv2.circle(m, (int(cx), int(cy)), r, (40, 40, 230), -1, cv2.LINE_AA)
        hx, hy = cx + math.cos(heading) * r * 2, cy - math.sin(heading) * r * 2
        cv2.line(m, (int(cx), int(cy)), (int(hx), int(hy)), (255, 255, 255), 1, cv2.LINE_AA)
        h, w = m.shape[:2]
        pad = 8
        roi = img[pad:pad + h, img.shape[1] - pad - w:img.shape[1] - pad]
        cv2.addWeighted(m, 0.85, roi, 0.15, 0, dst=roi)


# --- the robot client ------------------------------------------------------------

class Replaced(Exception):
    """The hub gave the robot slot to another robot (close code 4001)."""


class VirtualRobot(RobotSim):
    """/ws/robot client "virtual". Reuses robot_sim's cmd handling and watchdog."""

    def __init__(self, hub="ws://127.0.0.1:8765/ws/robot", world=DEFAULT_WORLD, fps=20, minimap=False):
        self.world = world if isinstance(world, World) else World.load(world)
        super().__init__(hub=hub, video="virtual", fps=fps, max_speed=self.world.max_speed)
        self.x, self.y, self.heading = self.world.spawn
        self.collision = False
        self.renderer = Renderer(self.world, minimap=minimap)
        self.frames_sent = self.frames_skipped = 0

    def _advance(self, now, previous):
        self._check_watchdog(now)
        dt = min(now - previous, 0.25)
        pose = [self.x, self.y, self.heading]
        self.collision = step(pose, self.vx * self.max_speed, self.vy * self.max_speed, dt,
                              self.world.radius, self.world.boxes)
        self.x, self.y = pose[0], pose[1]

    def encode(self, x, y, heading):
        ok, jpg = cv2.imencode(".jpg", self.renderer.render(x, y, heading),
                               [cv2.IMWRITE_JPEG_QUALITY, 70])
        if not ok:
            raise RuntimeError("JPEG encode failed")
        return jpg.tobytes()

    def telemetry(self):
        return {"type": "telemetry", "vx": self.vx, "vy": self.vy,
                "watchdog_stopped": self.watchdog_stopped, "battery_v": None,
                "x": round(self.x, 4), "y": round(self.y, 4), "heading": round(self.heading, 4),
                "collision": self.collision}

    @staticmethod
    def _link_busy(ws):
        # Never queue frames behind each other: if the last send hasn't left
        # the socket buffer yet, this frame waits for the next free moment.
        transport = getattr(ws, "transport", None)
        return transport is not None and transport.get_write_buffer_size() > 0

    async def _tick(self, ws):
        previous = time.monotonic()
        next_video = next_telemetry = previous
        while True:
            now = time.monotonic()
            self._advance(now, previous)
            previous = now
            if now >= next_telemetry:
                await ws.send(json.dumps(self.telemetry()))
                next_telemetry = now + 0.1
            if now >= next_video:
                if self._link_busy(ws):
                    self.frames_skipped += 1
                else:
                    # Render off the event loop (OpenCV releases the GIL), so
                    # cmds, pings and the watchdog aren't held up by a frame.
                    frame = await asyncio.to_thread(self.encode, self.x, self.y, self.heading)
                    await ws.send(frame)
                    self.frames_sent += 1
                    next_video = max(next_video + 1 / self.fps, time.monotonic() - 0.5 / self.fps)
            wake = min(next_video, next_telemetry) - time.monotonic()
            await asyncio.sleep(min(0.02, max(0.001, wake)))

    async def session(self, ws):
        self.drive(0, 0)
        self.last_cmd = None
        self.watchdog_stopped = True
        await ws.send(json.dumps({"type": "hello", "client": "robot", "name": "virtual",
                                  "video": {"w": self.renderer.cam.w, "h": self.renderer.cam.h,
                                            "fps": self.fps}}))
        tasks = [asyncio.create_task(self._receive(ws)), asyncio.create_task(self._tick(ws)),
                 asyncio.create_task(self._watchdog())]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except ConnectionClosed:
            pass
        finally:
            for task in tasks:
                task.cancel()
                with suppress(asyncio.CancelledError, ConnectionClosed):
                    await task
            self.drive(0, 0)
            self.watchdog_stopped = True
        rcvd = ws.close_code
        if rcvd == 4001 or "replac" in (ws.close_reason or ""):
            raise Replaced()

    async def run(self):
        delay = 0.5
        while True:
            try:
                async with connect(self.hub, max_size=None) as ws:
                    print(f"Virtual robot connected to {self.hub}", flush=True)
                    delay = 0.5
                    await self.session(ws)
            except Replaced:
                # Another robot has the slot. Fighting for it would kick
                # that robot off and start a reconnect war: stop instead.
                print("Another robot took the /ws/robot slot; virtual robot exiting.", flush=True)
                return
            except (OSError, ConnectionClosed) as exc:
                print(f"Robot link lost: {exc}; retrying in {delay:.1f}s", flush=True)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 5)


def main(argv=None):
    parser = argparse.ArgumentParser(description="NeuroMech virtual robot (CPU-rendered, no browser)")
    parser.add_argument("--hub", default="ws://127.0.0.1:8765/ws/robot")
    parser.add_argument("--world", default=str(DEFAULT_WORLD))
    parser.add_argument("--fps", type=float, default=20)
    parser.add_argument("--minimap", action="store_true", help="small top-down map in the corner")
    parser.add_argument("--exit-with-parent", action="store_true",
                        help="exit when stdin closes (used by `python -m hub --virtual-robot`)")
    args = parser.parse_args(argv)
    if args.fps <= 0:
        parser.error("--fps must be positive")
    if args.exit_with_parent:
        def watch_stdin():
            sys.stdin.read()                 # returns at EOF: the hub is gone
            os._exit(0)
        threading.Thread(target=watch_stdin, daemon=True).start()
    try:
        asyncio.run(VirtualRobot(hub=args.hub, world=args.world, fps=args.fps,
                                 minimap=args.minimap).run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
