"""Phase 2 measurements against a running `hub --device sim` on 127.0.0.1:18931 (no robot needed)."""
import asyncio, json, statistics, struct, time
import numpy as np, cv2, websockets
import os
HUB = os.environ.get("HUB", "127.0.0.1:18931")

async def latencies():
    async with websockets.connect(f"ws://{HUB}/ws/dashboard") as d:
        st = {}
        async def reader():
            async for m in d:
                m = json.loads(m)
                if m["type"] == "state": st.update(m)
        rt = asyncio.create_task(reader())
        async def wait(pred, timeout=10):
            t0 = time.monotonic()
            while time.monotonic() - t0 < timeout:
                if st and pred(st): return time.monotonic() - t0
                await asyncio.sleep(0.02)
            return None
        await asyncio.sleep(1)
        print("margin", st["params"]["margin"], "dwell", st["params"]["dwell"])
        await d.send(json.dumps({"type": "arm", "armed": True})); await wait(lambda s: s["armed"])
        on, off = [], []
        for i in range(12):
            tgt = ["up", "down", "left", "right"][i % 4]
            await d.send(json.dumps({"type": "sim_gaze", "target": tgt}))
            on.append(await wait(lambda s: s["command"]["direction"] == tgt))
            await asyncio.sleep(1.0)
            await d.send(json.dumps({"type": "sim_gaze", "target": None}))
            off.append(await wait(lambda s: s["command"]["direction"] is None))
            await asyncio.sleep(3.5)
        # look-away false motion, 60 s
        mv = n = ep = 0; prev = False; t0 = time.monotonic()
        while time.monotonic() - t0 < 60:
            m = st["command"]["direction"] is not None; mv += m; n += 1; ep += m and not prev; prev = m
            await asyncio.sleep(0.1)
        await d.send(json.dumps({"type": "arm", "armed": False}))
        rt.cancel()
        f = lambda xs: "median %.2f s, range %.2f-%.2f (n=%d, misses %d)" % (statistics.median([x for x in xs if x]), min(x for x in xs if x), max(x for x in xs if x), len(xs), xs.count(None))
        print("gaze -> motion:", f(on)); print("look away -> stop:", f(off))
        print("look-away false motion: %.1f%% of time, %d episodes in 60 s" % (100 * mv / n, ep))

def jpeg_with_time():
    img = np.full((480, 640, 3), 90, np.uint8); cv2.putText(img, str(time.time()), (20, 240), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
    ok, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70]); b = enc.tobytes()
    payload = b"NMTS" + struct.pack("<d", time.perf_counter())
    return b[:2] + b"\xff\xfe" + struct.pack(">H", len(payload) + 2) + payload + b[2:]   # COM segment after SOI

async def relay():
    lat = []
    async with websockets.connect(f"ws://{HUB}/ws/robot", max_size=None) as r, websockets.connect(f"ws://{HUB}/ws/video", max_size=None) as v:
        await r.send(json.dumps({"type": "hello", "client": "robot", "name": "sim"}))
        async def drain():
            async for m in r:
                if isinstance(m, str) and json.loads(m).get("type") == "ping":
                    await r.send(json.dumps({"type": "pong", "t_hub": json.loads(m)["t_hub"]}))
        async def view():
            async for b in v:
                if isinstance(b, bytes):
                    i = b.find(b"NMTS")
                    if i > 0: lat.append((time.perf_counter() - struct.unpack("<d", b[i + 4:i + 12])[0]) * 1000)
        tasks = [asyncio.create_task(drain()), asyncio.create_task(view())]
        for _ in range(200):
            await r.send(jpeg_with_time())
            await r.send(json.dumps({"type": "telemetry", "vx": 0, "vy": 0, "watchdog_stopped": True}))
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.5)
        for t in tasks: t.cancel()
    lat.sort()
    print("hub video relay robot->viewer: n=%d median %.1f ms, p95 %.1f ms, max %.1f ms" % (len(lat), lat[len(lat)//2], lat[int(len(lat)*.95)], lat[-1]))

import sys
if 'relay' not in sys.argv: asyncio.run(latencies())
asyncio.run(relay())
