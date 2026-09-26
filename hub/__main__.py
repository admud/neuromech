"""Run the PC hub: python -m hub [options]."""

import argparse
import subprocess
import sys
import threading
import time
import urllib.request

import uvicorn

from .netinfo import lan_ipv4_addresses
from .server import create_app


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="NeuroMech PC hub")
    parser.add_argument("--device", choices=("cyton", "synthetic", "sim"), default="cyton")
    parser.add_argument("--port", help="OpenBCI USB dongle COM port")
    parser.add_argument("--freqs", default="11,14,17,20", help="up,down,left,right frequencies")
    parser.add_argument("--window", type=float, default=3.0)
    parser.add_argument("--margin", type=float, default=0.08)
    parser.add_argument("--dwell", type=int, default=2)
    parser.add_argument("--speed", type=float, default=0.3)
    parser.add_argument("--model")
    parser.add_argument("--mode", default="trca_cca")
    parser.add_argument("--http-port", type=int, default=8765)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--control", choices=("hold", "latch"), default="hold",
                        help="hold: gaze drives while held; latch: gaze selects, a jaw clench latches/stops")
    parser.add_argument("--clench-threshold", type=float, default=8.0,
                        help="clench detector robust-z threshold (record_clench analyze suggests one)")
    parser.add_argument("--latch-max", type=float, default=3.0,
                        help="seconds a latch lasts at most before it releases itself")
    parser.add_argument("--stub", action="store_true")
    parser.add_argument("--virtual-robot", action="store_true",
                        help="also run the CPU-rendered virtual robot (hub.sim.virtual), no browser needed")
    args = parser.parse_args(argv)
    try:
        args.freqs = dict(zip(("up", "down", "left", "right"),
                              [float(part) for part in args.freqs.split(",")], strict=True))
    except (ValueError, TypeError):
        parser.error("--freqs must contain four comma-separated numbers")
    return args


def start_virtual_robot(port):
    """Start hub.sim.virtual once the server answers; returns a holder for the process.

    A child process, not a thread: its rendering then never competes with
    the hub's event loop for the GIL."""
    holder = {"proc": None, "stop": False}

    def launch():
        url = f"http://127.0.0.1:{port}/api/health"
        for _ in range(300):                 # wait up to ~30 s for the server
            if holder["stop"]:
                return
            try:
                with urllib.request.urlopen(url, timeout=1):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            print("Virtual robot not started: the hub never answered.", file=sys.stderr, flush=True)
            return
        if not holder["stop"]:
            # stdin is a pipe only the hub holds: if the hub dies without
            # cleaning up, the child sees EOF and exits instead of lingering.
            holder["proc"] = subprocess.Popen([sys.executable, "-m", "hub.sim.virtual",
                                               "--hub", f"ws://127.0.0.1:{port}/ws/robot",
                                               "--exit-with-parent"], stdin=subprocess.PIPE)
            print("Virtual robot started (hub.sim.virtual).", flush=True)

    threading.Thread(target=launch, name="virtual-robot-launcher", daemon=True).start()
    return holder


def stop_virtual_robot(holder):
    holder["stop"] = True
    proc = holder["proc"]
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


def main(argv=None):
    args = parse_args(argv)
    if args.stub:
        from .stub_engine import StubEngine
        from types import SimpleNamespace
        settings = SimpleNamespace(freqs=args.freqs, window_s=args.window,
                                   margin=args.margin, dwell=args.dwell, speed=args.speed)
        engine = StubEngine(settings)
    else:
        # Keep the stub available before Phase 1B has landed.
        from .bci.config import EngineSettings
        from .bci.engine import BciEngine
        settings = EngineSettings(device=args.device, port=args.port, freqs=args.freqs,
                                  window_s=args.window, margin=args.margin,
                                  dwell=args.dwell, speed=args.speed,
                                  model_path=args.model, mode=args.mode,
                                  control_mode=args.control,
                                  clench_threshold=args.clench_threshold,
                                  latch_max_s=args.latch_max)
        engine = BciEngine(settings)
    try:
        engine.start()
    except Exception as exc:
        print(f"Hub engine could not start: {exc}", file=sys.stderr)
        return 1
    addresses = lan_ipv4_addresses() or ["127.0.0.1"]
    for ip in addresses:
        print(f"Phone:     http://{ip}:{args.http_port}/phone/", flush=True)
        print(f"Dashboard: http://{ip}:{args.http_port}/dashboard/", flush=True)
    print("If the phone can't connect, allow Python through Windows Firewall on Public networks.", flush=True)
    virtual = start_virtual_robot(args.http_port) if args.virtual_robot else None
    try:
        uvicorn.run(create_app(engine, args.http_port), host=args.host, port=args.http_port,
                    ws="wsproto", log_level="info")
    finally:
        if virtual is not None:
            stop_virtual_robot(virtual)
        engine.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
