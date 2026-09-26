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
    parser.add_argument("--video", default="test",
                        help="test (a test pattern), none, or the rover's camera: a device number "
                             "(e.g. 1 for a USB video receiver) or a stream URL, "
                             "e.g. http://NeuroMech.local:8000/stream.mjpg")
    parser.add_argument("--freeze-settle", type=float, default=1.0,
                        help="seconds to keep the frozen frame after the rover stops, "
                             "while the camera recovers from the brown-out")
    parser.add_argument("--no-freeze", action="store_true",
                        help="show the live feed while driving too")
    parser.add_argument("--swap-lr", action="store_true",
                        help="send RIGHT for left and LEFT for right (the rover strafes the wrong way)")
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
