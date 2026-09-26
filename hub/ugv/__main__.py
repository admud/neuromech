"""Run the UGV UDP bridge: python -m hub.ugv [options]."""

import argparse
import asyncio
import sys

from .bridge import UgvBridge


def main(argv=None):
    parser = argparse.ArgumentParser(description="NeuroMech UGV UDP bridge")
    parser.add_argument("--hub", default="ws://127.0.0.1:8765/ws/robot")
    parser.add_argument("--host", default="NeuroMech.local")
    parser.add_argument("--port", type=int, default=5005)
    parser.add_argument("--repeat", type=float, default=0.2,
                        help="seconds between repeats of the current direction; the Pi brakes after 0.6 s of silence")
    parser.add_argument("--video", choices=("test", "none"), default="test")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        bridge = UgvBridge(**vars(args))
    except ValueError as exc:
        print(f"UGV bridge: {exc}", file=sys.stderr)
        return 2
    try:
        asyncio.run(bridge.run())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
