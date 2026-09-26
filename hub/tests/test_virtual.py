import asyncio
import json
import math
import time

import cv2
import numpy as np
import pytest
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from hub.sim.virtual import (CAMERA_X, Camera, Renderer, VirtualRobot, World, clip_near,
                             resolve, step)


def small_world(**extra):
    data = {"arena": {"size": [6.0, 4.0]}, "spawn": {"x": -2.5, "y": 0.0, "heading": 0.0},
            "robot": {"radius": 0.15, "max_speed_mps": 0.5,
                      "camera": {"height_m": 0.25, "pitch_deg": -10, "hfov_deg": 70, "w": 640, "h": 480}},
            "walls": [{"x": -1.2, "y": 0.7, "w": 0.1, "d": 2.6, "h": 0.4, "yaw_deg": 0}]}
    data.update(extra)
    return World(data)


# --- projection -------------------------------------------------------------

def test_camera_centre_horizon_and_sides():
    cam = Camera({"height_m": 0.25, "pitch_deg": -10, "hfov_deg": 70, "w": 640, "h": 480})
    origin, axes = cam.basis(0.0, 0.0, 0.0)
    assert np.allclose(origin, [CAMERA_X, 0, 0.25])
    # A point along the optical axis lands in the image centre.
    ahead = origin + 2.0 * axes[2]
    assert np.allclose(cam.project(cam.to_cam([ahead], origin, axes)), [[320, 240]], atol=1e-6)
    # Far away at camera height = the horizon, above centre because we look down.
    far = cam.project(cam.to_cam([[1000.0, 0, 0.25]], origin, axes))[0]
    assert far[1] == pytest.approx(240 - cam.f * math.tan(math.radians(10)), abs=0.5)
    # +y is the robot's left, so it appears on the left of the image.
    left = cam.project(cam.to_cam([[2.0, 0.5, 0.0]], origin, axes))[0]
    right = cam.project(cam.to_cam([[2.0, -0.5, 0.0]], origin, axes))[0]
    assert left[0] < 320 < right[0]
    # hfov: a point at the half-angle lands on the image edge.
    edge = [origin[0] + 1.0, origin[1] - math.tan(math.radians(35)), origin[2]]
    pc = cam.to_cam([edge], origin, axes)
    assert cam.project(pc)[0][0] == pytest.approx(640, abs=0.5 + 640 * 0.02)


def test_camera_follows_heading():
    cam = Camera({"height_m": 0.25, "pitch_deg": 0, "hfov_deg": 70, "w": 640, "h": 480})
    origin, axes = cam.basis(1.0, 2.0, math.pi / 2)        # facing +y
    assert np.allclose(origin, [1.0, 2.0 + CAMERA_X, 0.25])
    assert np.allclose(axes[2], [0, 1, 0], atol=1e-9)
    assert np.allclose(axes[0], [1, 0, 0], atol=1e-9)       # right of +y is +x


def test_near_clip_keeps_visible_part():
    poly = np.array([[0, 0, -1.0], [1, 0, 1.0], [0, 1, 1.0]])
    clipped = clip_near(poly)
    assert clipped is not None and (clipped[:, 2] >= 0.03 - 1e-9).all()
    assert clip_near(np.array([[0, 0, -1.0], [1, 0, -1.0], [0, 1, -2.0]])) is None


def test_render_shows_wall_ahead_and_meets_budget():
    world = small_world()
    r = Renderer(world, minimap=True)
    img = r.render(-2.5, 0.0, 0.0)
    assert img.shape == (480, 640, 3) and img.dtype == np.uint8
    # The wall (default colour) fills the image centre; the floor is below it.
    assert np.abs(img[240, 320].astype(int) - np.array((153, 144, 138))).max() < 90
    assert img[470, 250].mean() > 150                     # floor tile, off the y = 0 grid line
    times = []
    for i in range(40):
        t = time.perf_counter()
        ok, _ = cv2.imencode(".jpg", r.render(-2.5 + 0.02 * i, 0.3 * math.sin(i), 0.0),
                             [cv2.IMWRITE_JPEG_QUALITY, 70])
        times.append(time.perf_counter() - t)
        assert ok
    assert np.median(times) < 0.015


# --- kinematics and collisions ------------------------------------------------

def test_mecanum_motion_axes():
    world = small_world(walls=[])
    for (vx, vy), (ex, ey) in {(1, 0): (0.5, 0), (-1, 0): (-0.5, 0), (0, 1): (0, 0.5), (0, -1): (0, -0.5)}.items():
        pose = [0.0, 0.0, 0.0]
        for _ in range(100):
            step(pose, vx * 0.5, vy * 0.5, 0.01, 0.15, world.boxes)
        assert pose[0] == pytest.approx(ex, abs=1e-9) and pose[1] == pytest.approx(ey, abs=1e-9)


def test_robot_frame_rotates_with_heading():
    pose = [0.0, 0.0, math.pi / 2]
    step(pose, 0.5, 0.0, 1.0, 0.15, [])                     # forward while facing +y
    assert pose[0] == pytest.approx(0, abs=1e-9) and pose[1] == pytest.approx(0.5)


def test_wall_stops_and_reports_collision():
    world = small_world()
    pose = [-2.5, 0.0, 0.0]
    hit = False
    for _ in range(400):
        hit = step(pose, 0.5, 0.0, 0.01, 0.15, world.boxes)
    assert pose[0] == pytest.approx(-1.25 - 0.15, abs=1e-6)
    assert hit


def test_slides_along_wall():
    world = small_world()
    pose = [-1.4, 0.0, 0.0]                                 # touching the wall's face
    for _ in range(100):
        step(pose, 0.5, -0.5, 0.01, 0.15, world.boxes)       # into the wall and to the right
    assert pose[1] == pytest.approx(-0.5, abs=1e-6)          # sideways motion kept
    # It got past the wall's end (y = -0.6) or is still pressed to its face.
    assert pose[0] <= -1.4 + 1e-6 or pose[1] < -0.6


def test_resolve_escapes_from_inside_a_box():
    boxes = small_world().boxes
    x, y, hit = resolve(-1.2, 0.7, 0.15, boxes)
    assert hit and (abs(x + 1.2) >= 0.05 + 0.15 - 1e-6)


def test_rotated_box_collision():
    world = World({"arena": {"size": [6, 4]},
                   "walls": [{"x": 0, "y": 0, "w": 1.0, "d": 0.2, "h": 0.3, "yaw_deg": 90}]})
    pose = [-1.0, 0.0, 0.0]
    for _ in range(400):
        step(pose, 0.5, 0.0, 0.01, 0.15, world.boxes)
    # Rotated 90°, the 0.2 m side faces the robot: stops at x = -0.1 - r.
    assert pose[0] == pytest.approx(-0.25, abs=1e-6)


def test_perimeter_keeps_robot_inside():
    world = small_world(walls=[])
    pose = [2.5, 1.5, 0.0]
    for _ in range(400):
        step(pose, 0.5, 0.5, 0.01, 0.15, world.boxes)
    assert pose[0] == pytest.approx(3 - 0.15, abs=1e-6) and pose[1] == pytest.approx(2 - 0.15, abs=1e-6)


def test_default_world_loads():
    world = World.load(str(__import__("hub.sim.virtual", fromlist=["x"]).DEFAULT_WORLD))
    assert len(world.boxes) >= 4 and world.max_speed > 0 and world.camera["w"] == 640


# --- protocol against a fake hub ----------------------------------------------------

def test_protocol_hello_cmd_frames_telemetry_watchdog_pong():
    asyncio.run(_exercise_protocol())


async def _exercise_protocol():
    seen = {"frames": 0, "telemetry": [], "pong": None}

    async def handler(ws):
        hello = json.loads(await ws.recv())
        assert hello["type"] == "hello" and hello["client"] == "robot" and hello["name"] == "virtual"
        assert hello["video"] == {"w": 640, "h": 480, "fps": 20}
        await ws.send(json.dumps({"type": "ping", "t_hub": 12.5}))
        t0 = time.monotonic()
        seq = 0
        while time.monotonic() - t0 < 1.4:
            # Drive left for 0.6 s at 10 Hz, then stop sending: watchdog must stop it.
            if time.monotonic() - t0 < 0.6 and time.monotonic() - t0 >= seq * 0.1:
                seq += 1
                await ws.send(json.dumps({"type": "cmd", "seq": seq, "vx": 0, "vy": 1, "ttl_ms": 300}))
            try:
                msg = await asyncio.wait_for(ws.recv(), 0.05)
            except asyncio.TimeoutError:
                continue
            if isinstance(msg, bytes):
                assert msg[:2] == b"\xff\xd8"
                seen["frames"] += 1
            else:
                m = json.loads(msg)
                if m["type"] == "telemetry":
                    seen["telemetry"].append(m)
                elif m["type"] == "pong":
                    seen["pong"] = m
        await ws.close()

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        robot = VirtualRobot(hub=f"ws://127.0.0.1:{port}", world=small_world(walls=[]), fps=20)
        async with connect(robot.hub, max_size=None) as ws:
            await robot.session(ws)

    tel = seen["telemetry"]
    assert seen["pong"] == {"type": "pong", "t_hub": 12.5}
    assert 18 <= seen["frames"] <= 32                        # ~20 fps over 1.4 s
    assert 10 <= len(tel) <= 18                              # ~10 Hz
    assert {"vx", "vy", "watchdog_stopped", "battery_v", "x", "y", "heading", "collision"} <= set(tel[0])
    moving = [m for m in tel if m["vy"] == 1]
    assert moving and not moving[0]["watchdog_stopped"]
    assert tel[-1]["y"] > 0.2                                # moved left (+y)
    assert tel[-1]["watchdog_stopped"] and tel[-1]["vy"] == 0
    # Stopped: the last two reports have the same pose.
    assert tel[-1]["y"] == tel[-2]["y"]


def test_exits_when_replaced():
    async def scenario():
        connections = 0

        async def handler(ws):
            nonlocal connections
            connections += 1
            await ws.recv()                                  # hello
            await ws.close(code=4001, reason="replaced")

        async with serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            robot = VirtualRobot(hub=f"ws://127.0.0.1:{port}", world=small_world(), fps=20)
            await asyncio.wait_for(robot.run(), 3)           # returns instead of reconnecting
        return connections

    assert asyncio.run(scenario()) == 1


def test_reconnects_after_ordinary_close():
    async def scenario():
        connections = 0

        async def handler(ws):
            nonlocal connections
            connections += 1
            await ws.recv()
            await ws.close()

        async with serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            robot = VirtualRobot(hub=f"ws://127.0.0.1:{port}", world=small_world(), fps=20)
            task = asyncio.create_task(robot.run())
            await asyncio.sleep(1.4)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        return connections

    assert asyncio.run(scenario()) >= 2
