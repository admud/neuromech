"""python -m hub.gui: desktop operator display (robot video + SSVEP circles).

Examples (from the repo root):
  control\\.venv\\Scripts\\python -m hub.gui                       # full screen, screen 0, hub on this PC
  control\\.venv\\Scripts\\python -m hub.gui --screen 1
  control\\.venv\\Scripts\\python -m hub.gui --windowed --log-frames frames.csv --duration 20
  control\\.venv\\Scripts\\python -m hub.gui.analyze frames.csv     # check real flip timing + frequencies
"""
import argparse

from .app import App


def parse_size(text):
    w, _, h = text.lower().partition("x")
    return int(w), int(h)


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m hub.gui", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--hub", default="127.0.0.1:8765", help="hub host:port")
    p.add_argument("--screen", type=int, default=0, help="display index (listed at startup)")
    p.add_argument("--windowed", action="store_true", help="window instead of full screen (testing)")
    p.add_argument("--win-size", type=parse_size, default=(1280, 720), help="window size with --windowed, e.g. 1280x720")
    p.add_argument("--size", type=float, default=0.16, help="circle diameter as a fraction of the short side")
    p.add_argument("--no-video", action="store_true", help="flicker only, for timing tests")
    p.add_argument("--log-frames", metavar="FILE", help="write every frame's flip time and levels to a CSV at exit")
    p.add_argument("--duration", type=float, default=0, help="quit after this many seconds (0 = run until Q)")
    p.add_argument("--script", help=argparse.SUPPRESS)   # synthetic key events, see app.Script
    p.add_argument("--screenshot", help=argparse.SUPPRESS)   # file for the script's "shot" action
    args = p.parse_args(argv)
    print("NeuroMech desktop display")
    App(args).run()


if __name__ == "__main__":
    main()
