"""FastAPI hub routes and live protocol fan-out."""

import asyncio
import json
import math
import mimetypes
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .netinfo import lan_ipv4_addresses
from .video import VideoRelay


ROOT = Path(__file__).resolve().parent.parent
IDLE_TIMEOUT_S = 3.0
mimetypes.add_type("text/javascript", ".js")


class Peer:
    def __init__(self, websocket):
        self.ws = websocket
        self.lock = asyncio.Lock()

    async def send(self, message):
        async with self.lock:
            await self.ws.send_json(message)


def create_app(engine, http_port=8765):
    phones = set()
    dashboards = set()
    video = VideoRelay()
    robot = {"peer": None, "name": None, "telemetry": {}, "rtt_ms": None,
             "ping_at": None}
    phone_stats = {"fps": None, "p95_ms": None, "dropped": None, "rtt_ms": None}
    seq = 0

    async def drop_phone(peer):
        phones.discard(peer)
        if not phones:
            engine.set_phone_connected(False)

    async def close_stale(ws):
        with suppress(Exception):
            await asyncio.wait_for(ws.close(code=1001), timeout=0.08)

    def retire_robot(peer):
        if robot["peer"] is peer:
            robot.update(peer=None, name=None, telemetry={}, rtt_ms=None, ping_at=None)
            engine.set_robot_connected(False)

    async def fanout(peers, message):
        for peer in tuple(peers):
            try:
                await asyncio.wait_for(peer.send(message), timeout=0.08)
            except Exception:
                peers.discard(peer)
                with suppress(Exception):
                    await asyncio.wait_for(peer.ws.close(), timeout=0.08)
                if peers is phones:
                    await drop_phone(peer)

    async def broadcast_config():
        await fanout(phones, engine.config_message())
        await fanout(dashboards, engine.config_message())

    ips = lan_ipv4_addresses()
    host = ips[0] if ips else "localhost"

    async def state_loop():
        while True:
            start = time.monotonic()
            state = {"type": "state", "t_hub": start, **engine.status(),
                     "phone": {"connected": bool(phones), **phone_stats},
                     "robot": {"connected": robot["peer"] is not None,
                               "name": robot["name"], "rtt_ms": robot["rtt_ms"],
                               "telemetry": robot["telemetry"]},
                     "video": video.status(),
                     "hub": {"phone_url": f"http://{host}:{http_port}/phone/",
                             "dashboard_url": f"http://{host}:{http_port}/dashboard/"}}
            await fanout(phones, state)
            await fanout(dashboards, state)
            await asyncio.sleep(max(0, start + 0.1 - time.monotonic()))

    @asynccontextmanager
    async def lifespan(_app):
        task = asyncio.create_task(state_loop())
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    app = FastAPI(lifespan=lifespan)
    app.state.video = video
    for name in ("phone", "dashboard", "twin"):
        path = ROOT / "web" / name
        if path.is_dir():
            app.mount(f"/{name}", StaticFiles(directory=path, html=True), name=name)

    @app.get("/")
    def root():
        return RedirectResponse("/phone/")

    @app.get("/api/health")
    def health():
        return {"ok": True}

    async def receive_json(ws):
        data = await ws.receive_text()
        try:
            value = json.loads(data)
        except (ValueError, TypeError):
            return {}
        return value if isinstance(value, dict) else {}

    @app.websocket("/ws/phone")
    async def ws_phone(ws: WebSocket):
        await ws.accept()
        peer = Peer(ws)
        await peer.send(engine.config_message())
        phones.add(peer)
        if len(phones) == 1:
            engine.set_phone_connected(True)
        last_message = time.monotonic()
        try:
            while True:
                remaining = max(0.001, last_message + IDLE_TIMEOUT_S - time.monotonic())
                msg = await asyncio.wait_for(receive_json(ws), timeout=remaining)
                last_message = time.monotonic()
                kind = msg.get("type")
                if kind == "frame_stats":
                    for key in ("fps", "p95_ms", "dropped", "rtt_ms"):
                        if isinstance(msg.get(key), (int, float)) and math.isfinite(msg[key]):
                            phone_stats[key] = msg[key]
                elif kind == "arm":
                    engine.handle(msg, "phone")
                elif kind == "ping":
                    await peer.send({"type": "pong", "t_client": msg.get("t_client"),
                                     "t_hub": time.monotonic()})
        except (WebSocketDisconnect, RuntimeError):
            pass
        except asyncio.TimeoutError:
            await close_stale(ws)
        finally:
            await drop_phone(peer)

    @app.websocket("/ws/dashboard")
    async def ws_dashboard(ws: WebSocket):
        await ws.accept()
        peer = Peer(ws)
        await peer.send(engine.config_message())
        dashboards.add(peer)
        try:
            while True:
                msg = await receive_json(ws)
                kind = msg.get("type")
                if kind in ("arm", "set_config", "override", "sim_gaze"):
                    if engine.handle(msg, "dashboard"):
                        await broadcast_config()
                elif kind == "ping":
                    await peer.send({"type": "pong", "t_client": msg.get("t_client"),
                                     "t_hub": time.monotonic()})
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            dashboards.discard(peer)

    @app.websocket("/ws/video")
    async def ws_video(ws: WebSocket):
        await ws.accept()
        sender = asyncio.create_task(video.serve(ws))
        try:
            while True:
                message = await ws.receive()
                if message["type"] == "websocket.disconnect":
                    break
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            sender.cancel()
            with suppress(asyncio.CancelledError, RuntimeError, WebSocketDisconnect):
                await sender

    async def robot_send(peer):
        nonlocal seq
        next_ping = 0.0
        try:
            while robot["peer"] is peer:
                start = time.monotonic()
                command = engine.command()
                seq += 1
                await asyncio.wait_for(peer.send({"type": "cmd", "seq": seq,
                                                  "vx": command["vx"], "vy": command["vy"],
                                                  "ttl_ms": 500}), timeout=0.08)
                if start >= next_ping:
                    robot["ping_at"] = start
                    await asyncio.wait_for(peer.send({"type": "ping", "t_hub": start}),
                                           timeout=0.08)
                    next_ping = start + 1
                await asyncio.sleep(max(0, start + 0.1 - time.monotonic()))
        except Exception:
            retire_robot(peer)
            with suppress(Exception):
                await asyncio.wait_for(peer.ws.close(), timeout=0.08)

    @app.websocket("/ws/robot")
    async def ws_robot(ws: WebSocket):
        await ws.accept()
        peer = Peer(ws)
        old = robot["peer"]
        if old is not None:
            with suppress(Exception):
                await asyncio.wait_for(old.ws.close(code=4001, reason="replaced"), timeout=0.08)
        robot.update(peer=peer, name=None, telemetry={}, rtt_ms=None, ping_at=None)
        engine.set_robot_connected(True)
        sender = asyncio.create_task(robot_send(peer))
        last_liveness = time.monotonic()
        try:
            while True:
                remaining = max(0.001, last_liveness + IDLE_TIMEOUT_S - time.monotonic())
                event = await asyncio.wait_for(ws.receive(), timeout=remaining)
                if event["type"] == "websocket.disconnect":
                    break
                if event.get("bytes") is not None:
                    if robot["peer"] is peer:
                        await video.publish(event["bytes"])
                    continue
                try:
                    msg = json.loads(event.get("text") or "")
                except (ValueError, TypeError):
                    continue
                if not isinstance(msg, dict) or robot["peer"] is not peer:
                    continue
                kind = msg.get("type")
                if kind == "hello":
                    robot["name"] = msg.get("name")
                elif kind == "telemetry":
                    last_liveness = time.monotonic()
                    robot["telemetry"] = {k: v for k, v in msg.items() if k != "type"}
                elif kind == "pong":
                    last_liveness = time.monotonic()
                    if isinstance(msg.get("t_hub"), (int, float)):
                        robot["rtt_ms"] = round((time.monotonic() - msg["t_hub"]) * 1000, 1)
        except (WebSocketDisconnect, RuntimeError):
            pass
        except asyncio.TimeoutError:
            await close_stale(ws)
        finally:
            sender.cancel()
            with suppress(asyncio.CancelledError):
                await sender
            retire_robot(peer)

    return app
