"""Run the PC hub: python -m hub [options]."""

import argparse
import sys

import uvicorn

from .netinfo import lan_ipv4_addresses
from .server import create_app


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="NeuroMech PC hub")
    parser.add_argument("--device", choices=("cyton", "synthetic", "sim"), default="cyton")
    parser.add_argument("--port", help="OpenBCI USB dongle COM port")
    parser.add_argument("--freqs", default="11,14,17,20", help="up,down,left,right frequencies")
    parser.add_argument("--window", type=float, default=3.0)
    parser.add_argument("--margin", type=float, default=0.06)
    parser.add_argument("--dwell", type=int, default=2)
    parser.add_argument("--speed", type=float, default=0.3)
    parser.add_argument("--model")
    parser.add_argument("--mode", default="trca_cca")
    parser.add_argument("--http-port", type=int, default=8765)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--stub", action="store_true")
    args = parser.parse_args(argv)
    try:
        args.freqs = dict(zip(("up", "down", "left", "right"),
                              [float(part) for part in args.freqs.split(",")], strict=True))
    except (ValueError, TypeError):
        parser.error("--freqs must contain four comma-separated numbers")
    return args


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
                                  model_path=args.model, mode=args.mode)
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
    try:
        uvicorn.run(create_app(engine, args.http_port), host=args.host, port=args.http_port,
                    ws="wsproto", log_level="info")
    finally:
        engine.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
