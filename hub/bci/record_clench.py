"""Record a labelled jaw-clench session from the Cyton, and analyse it offline.

    python -m hub.bci.record_clench --port COM8 --out clench_s1.npz
    python -m hub.bci.record_clench --out clench_s1.npz          # dongle auto-detected
    python -m hub.bci.record_clench analyze clench_s1.npz

The hub must NOT be running: only one program can hold the dongle.

The session (about 2 minutes) is cued in the terminal and by beeps, so you
don't have to watch the screen:
  1. rest     20 s   sit still, jaw relaxed, eyes on the screen
  2. clench   10 x   high beep = clench firmly (hold ~1 s), low beep = relax
  3. look     20 s   look at the top / right / bottom / left edge of the
                     screen as prompted, and clench on each high beep
  4. blink    10 s   look around and blink normally, do NOT clench
                     (false-alarm check)

Saved: the raw EEG of every channel (µV, board order), fs, channel names,
and markers (label, start, end sample) for every segment and cue.
"""
import argparse
import datetime
import os
import random
import sys
import threading
import time

import numpy as np

from . import board as boardmod
from .config import EngineSettings

CLENCH_HOLD_S = 1.0
RAIL_UV = 180000.0


def _beep(freq, ms):
    """Non-blocking beep, so cue timing isn't held up by the sound."""
    def run():
        try:
            import winsound
            winsound.Beep(freq, ms)
        except Exception:
            print("\a", end="", flush=True)
    threading.Thread(target=run, daemon=True).start()


def beep_clench():
    _beep(1200, 150)


def beep_relax():
    _beep(500, 150)


class Recorder:
    """Drains the board into memory and hands out sample indices for markers."""

    def __init__(self, ob, sim_clench=False):
        self.ob = ob
        self.rows = list(ob.all_rows or ob.ch_rows)
        self.names = list(ob.all_names or ob.ch_names)
        self.chunks = []
        self.n = 0
        self.markers = []   # (label, start, end)
        self.sim_clench = sim_clench

    def drain(self):
        d = self.ob.board.get_board_data()
        if d.shape[1]:
            self.chunks.append(np.asarray(d[self.rows], dtype=np.float32))
            self.n += d.shape[1]
        return self.n

    def wait(self, seconds):
        end = time.monotonic() + seconds
        while True:
            self.drain()
            left = end - time.monotonic()
            if left <= 0:
                return self.n
            time.sleep(min(0.05, left))

    def mark(self, label, start, end):
        self.markers.append((label, int(start), int(end)))

    def clench_cue(self, label):
        """One cued clench: high beep, hold, low beep. Returns (start, end) samples."""
        start = self.drain()
        beep_clench()
        if self.sim_clench:
            self.ob.board.clench(0.8)
        print("   CLENCH", flush=True)
        end = self.wait(CLENCH_HOLD_S)
        beep_relax()
        print("   relax", flush=True)
        self.mark(label, start, end)
        return start, end

    def data(self):
        if not self.chunks:
            return np.zeros((len(self.rows), 0), np.float32)
        return np.concatenate(self.chunks, axis=1)


def countdown(rec, seconds, label):
    """Wait `seconds`, printing the time left every 5 s."""
    end = time.monotonic() + seconds
    while True:
        left = end - time.monotonic()
        if left <= 0.05:
            break
        if int(round(left)) % 5 == 0:
            print("   %s: %2d s left" % (label, round(left)), flush=True)
        rec.wait(min(1.0, left))


def run_session(rec, rest_s, n_clench, look_s, blink_s):
    print("\n1/4  REST: sit still, jaw relaxed, eyes on the screen.", flush=True)
    rec.wait(2.0)
    beep_relax()
    s = rec.drain()
    countdown(rec, rest_s, "rest")
    rec.mark("rest", s, rec.drain())

    print("\n2/4  CLENCHES: high beep = clench firmly and hold, low beep = relax."
          " %d of them." % n_clench, flush=True)
    rec.wait(2.0)
    s = rec.drain()
    for i in range(n_clench):
        gap = random.uniform(2.5, 4.0)   # irregular, so you can't anticipate
        g0 = rec.drain()
        rec.wait(gap)
        rec.mark("relax", g0, rec.drain())
        print("  %d/%d" % (i + 1, n_clench), flush=True)
        rec.clench_cue("clench")
    rec.wait(2.0)
    rec.mark("clench_block", s, rec.drain())

    print("\n3/4  LOOK + CLENCH: look where you're told, clench on each high beep.", flush=True)
    rec.wait(2.0)
    s = rec.drain()
    t_end = time.monotonic() + look_s
    edges = ["TOP", "RIGHT", "BOTTOM", "LEFT"]
    k = 0
    while time.monotonic() < t_end - 3.0:
        print("   look at the %s edge" % edges[k % 4], flush=True)
        rec.wait(2.0)
        rec.clench_cue("look_clench")
        rec.wait(1.0)
        k += 1
    rec.wait(max(0.0, t_end - time.monotonic()))
    rec.mark("look", s, rec.drain())

    print("\n4/4  BLINK: look around and blink normally. Do NOT clench.", flush=True)
    rec.wait(1.0)
    beep_relax()
    s = rec.drain()
    countdown(rec, blink_s, "blink")
    rec.mark("blink", s, rec.drain())
    print("\nDone.", flush=True)


def save(path, rec, ob, meta):
    data = rec.data()
    labels = np.array([m[0] for m in rec.markers])
    np.savez_compressed(
        path, data=data, fs=int(ob.fs), ch_names=np.array(rec.names),
        marker_label=labels,
        marker_start=np.array([m[1] for m in rec.markers], dtype=np.int64),
        marker_end=np.array([m[2] for m in rec.markers], dtype=np.int64),
        device=ob.device, port=ob.port or "", created=meta["created"], version=1)
    return data


def load(path):
    d = np.load(path, allow_pickle=False)
    markers = list(zip([str(x) for x in d["marker_label"]],
                       d["marker_start"].tolist(), d["marker_end"].tolist()))
    return {"data": d["data"].astype(np.float64), "fs": int(d["fs"]),
            "ch_names": [str(c) for c in d["ch_names"]], "markers": markers,
            "device": str(d["device"])}


def record(args):
    settings = EngineSettings(device=args.device, port=args.port)
    try:
        ob = boardmod.open_board(settings)
    except boardmod.BoardError as exc:
        sys.exit(str(exc))
    print("%s%s @ %d Hz, channels %s" % (ob.device, " on %s" % ob.port if ob.port else "",
                                         ob.fs, ", ".join(ob.all_names or ob.ch_names)))
    ob.board.start_stream()
    rec = Recorder(ob, sim_clench=args.device == "sim")
    try:
        print("Settling 3 s ...", flush=True)
        rec.wait(3.0)
        rec.chunks, rec.n = [], 0          # drop the settle period
        rec.drain()
        run_session(rec, args.rest, args.clenches, args.look, args.blink)
    except KeyboardInterrupt:
        print("\nInterrupted: saving what was recorded.", flush=True)
    finally:
        rec.drain()
        for fn in (ob.board.stop_stream, ob.board.release_session):
            try:
                fn()
            except Exception:
                pass
    data = save(args.out, rec, ob, {"created": datetime.datetime.now().isoformat(timespec="seconds")})
    print("Saved %s: %d channels x %d samples (%.0f s), %d markers"
          % (args.out, data.shape[0], data.shape[1], data.shape[1] / ob.fs, len(rec.markers)))
    railed = [n for n, x in zip(rec.names, data) if x.size and np.max(np.abs(x)) > RAIL_UV]
    if railed:
        print("  ! railed (no contact?): %s" % ", ".join(railed))
    print("Next: python -m hub.bci.record_clench analyze %s" % args.out)


def analyze(args):
    from .clench import analyze_recording
    rec = load(args.file)
    channels = args.channels.split(",") if args.channels else None
    print(analyze_recording(rec, channels=channels, threshold=args.threshold))


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "analyze":
        p = argparse.ArgumentParser(prog="python -m hub.bci.record_clench analyze",
                                    description="Offline clench-vs-rest analysis of a recording.")
        p.add_argument("file")
        p.add_argument("--channels", default=None,
                       help="comma-separated channel names (default Fp1,Fp2,P7,P8)")
        p.add_argument("--threshold", type=float, default=None,
                       help="also report detections at this z threshold")
        analyze(p.parse_args(argv[1:]))
        return
    p = argparse.ArgumentParser(prog="python -m hub.bci.record_clench", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--device", default="cyton", choices=("cyton", "synthetic", "sim"))
    p.add_argument("--port", default=None, help="dongle COM port; default auto-detects it")
    p.add_argument("--out", default="clench_s1.npz")
    p.add_argument("--rest", type=float, default=20.0, help="seconds of rest")
    p.add_argument("--clenches", type=int, default=10, help="number of cued clenches")
    p.add_argument("--look", type=float, default=20.0, help="seconds of look + clench")
    p.add_argument("--blink", type=float, default=10.0, help="seconds of look + blink, no clench")
    args = p.parse_args(argv)
    if os.path.exists(args.out):
        sys.exit("%s already exists; pick another --out" % args.out)
    record(args)


if __name__ == "__main__":
    main()
