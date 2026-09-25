"""Run the eeg-expy visual SSVEP experiment on an 8-channel OpenBCI Cyton.

Usage:
    python run_ssvep.py --subject 1 --session 1 --run 1
    python run_ssvep.py --subject 1 --session 1 --run 2 --duration 120

Data is written to:
    ~/.eegnb/data/visual-SSVEP/local/cyton/subject000N/session00N/recording_<timestamp>.csv

which is the layout eegnb.analysis.analysis_utils.load_data expects, so the
analysis in examples/visual_ssvep/01r__ssvep_viz.py can read it directly.

Markers: 1 = the faster flicker, 2 = the slower flicker. On a 60 Hz display
these are 30 Hz and 20 Hz, matching the event_id map in the example analysis.
"""
import argparse
import ctypes
import sys

from eegnb import generate_save_fn
from eegnb.devices.eeg import EEG
from eegnb.experiments import VisualSSVEP

EXPERIMENT = "visual-SSVEP"  # matches the CLI + example-dataset folder naming


def current_refresh_rate():
    """Query the primary display's refresh rate via the Win32 API."""
    class DEVMODE(ctypes.Structure):
        _fields_ = [
            ("dmDeviceName", ctypes.c_wchar * 32), ("dmSpecVersion", ctypes.c_ushort),
            ("dmDriverVersion", ctypes.c_ushort), ("dmSize", ctypes.c_ushort),
            ("dmDriverExtra", ctypes.c_ushort), ("dmFields", ctypes.c_ulong),
            ("dmPositionX", ctypes.c_long), ("dmPositionY", ctypes.c_long),
            ("dmDisplayOrientation", ctypes.c_ulong), ("dmDisplayFixedOutput", ctypes.c_ulong),
            ("dmColor", ctypes.c_short), ("dmDuplex", ctypes.c_short),
            ("dmYResolution", ctypes.c_short), ("dmTTOption", ctypes.c_short),
            ("dmCollate", ctypes.c_short), ("dmFormName", ctypes.c_wchar * 32),
            ("dmLogPixels", ctypes.c_ushort), ("dmBitsPerPel", ctypes.c_ulong),
            ("dmPelsWidth", ctypes.c_ulong), ("dmPelsHeight", ctypes.c_ulong),
            ("dmDisplayFlags", ctypes.c_ulong), ("dmDisplayFrequency", ctypes.c_ulong),
            ("dmICMMethod", ctypes.c_ulong), ("dmICMIntent", ctypes.c_ulong),
            ("dmMediaType", ctypes.c_ulong), ("dmDitherType", ctypes.c_ulong),
            ("dmReserved1", ctypes.c_ulong), ("dmReserved2", ctypes.c_ulong),
            ("dmPanningWidth", ctypes.c_ulong), ("dmPanningHeight", ctypes.c_ulong),
        ]

    dm = DEVMODE()
    dm.dmSize = ctypes.sizeof(DEVMODE)
    ENUM_CURRENT_SETTINGS = -1

    fn = ctypes.windll.user32.EnumDisplaySettingsW
    fn.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong, ctypes.POINTER(DEVMODE)]
    fn.restype = ctypes.c_int

    if fn(None, ENUM_CURRENT_SETTINGS, ctypes.byref(dm)):
        return int(dm.dmDisplayFrequency), int(dm.dmPelsWidth), int(dm.dmPelsHeight)
    return None, None, None


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--subject", type=int, required=True, help="subject ID")
    p.add_argument("--session", type=int, required=True, help="session number")
    p.add_argument("--run", type=int, default=1, help="run/block number within the session (label only)")
    p.add_argument("--duration", type=float, default=120, help="recording duration in seconds")
    p.add_argument("--port", default="COM11", help="Cyton USB dongle serial port")
    p.add_argument("--windowed", action="store_true", help="run in a window instead of fullscreen")
    p.add_argument("--skip-refresh-check", action="store_true")
    args = p.parse_args()

    hz, w, h = current_refresh_rate()
    if hz:
        print(f"Display: {w}x{h} @ {hz} Hz")
        if hz != 60 and not args.skip_refresh_check:
            print(f"\n  !! Display is {hz} Hz, not 60 Hz.")
            print(f"  !! ssvep.py derives the stimuli as refresh/2 and refresh/3,")
            print(f"  !! so you would get {hz/2:.0f} Hz and {hz/3:.0f} Hz instead of 30 and 20 Hz,")
            print(f"  !! and the example analysis labels markers 1/2 as '30 Hz'/'20 Hz'.")
            print(f"  !! Set the display to 60 Hz, or pass --skip-refresh-check to record anyway.\n")
            sys.exit(1)

    print(f"\nConnecting to Cyton on {args.port} ...")
    eeg = EEG(device="cyton", serial_port=args.port)
    print(f"  backend={eeg.backend}  sfreq={eeg.sfreq}  channels={eeg.channels}")

    save_fn = generate_save_fn("cyton", EXPERIMENT, args.subject, args.session)
    print(f"\nRun {args.run}: recording {args.duration:.0f}s to\n  {save_fn}\n")

    ssvep = VisualSSVEP(duration=args.duration, eeg=eeg, save_fn=save_fn)
    if args.windowed:
        ssvep.use_fullscr = False

    print("A window will open. Fixate the red dot at the centre of the grating.")
    print("Press SPACE to begin, ESC to abort.\n")
    ssvep.run()

    print(f"\nDone. Saved:\n  {save_fn}")


if __name__ == "__main__":
    main()
