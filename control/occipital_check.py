"""Live signal-quality monitor focused on the channels that matter for SSVEP.

Usage:  python occipital_check.py [COM11]

Unlike `eegnb checksigqual`, this does not require all 8 electrodes to be good --
it gates on the occipital/parietal channels (O1, O2, P7, P8) and just reports the
rest. Ctrl-C to stop. Adjust electrodes while it runs and watch the numbers.
"""
import sys
from time import sleep

from eegnb.devices.eeg import EEG
from eegnb.analysis.streaming_utils import check

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM11"
KEY_CHANNELS = ["O1", "O2", "P7", "P8"]
LOW, HIGH = 1.0, 9.0  # OpenBCI thresholds from eegnb.analysis.utils.thres_stds
WINDOW_SEC = 2

eeg = EEG(device="cyton", serial_port=PORT)
n_samples = int(WINDOW_SEC * eeg.sfreq)

print(f"\nMonitoring {eeg.device_name} on {PORT} at {eeg.sfreq} Hz")
print(f"Gating on {', '.join(KEY_CHANNELS)} -- target stdev {LOW}-{HIGH} uV")
print("Below ~1 = electrode not making contact.  Above ~9 = loose/noisy/movement.")
print("Ctrl-C to stop.\n")

try:
    i = 0
    while True:
        i += 1
        std = check(eeg, n_samples=n_samples)
        key_bad = []
        line = []
        for name, v in std.items():
            ok = LOW <= v <= HIGH
            mark = "OK " if ok else ("LOW" if v < LOW else "HI ")
            star = "*" if name in KEY_CHANNELS else " "
            line.append(f"{star}{name}:{v:6.2f} {mark}")
            if name in KEY_CHANNELS and not ok:
                key_bad.append(name)
        print(f"[{i:3}] " + " | ".join(line))
        if key_bad:
            print(f"      -> fix: {', '.join(key_bad)}")
        else:
            print("      -> occipital channels all good. Ready to record SSVEP.")
        sleep(1)
except KeyboardInterrupt:
    print("\nStopping.")
finally:
    try:
        eeg.board.stop_stream()
        eeg.board.release_session()
    except Exception:
        pass
