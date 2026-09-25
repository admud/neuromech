"""Opening the EEG board: Cyton (auto-detected dongle), brainflow synthetic, or the SSVEP sim.

eegnb's `EEG(device="cyton", serial_port=None)` asks for the port with
input(), which would hang the hub, so the port is always resolved here first.
"""
from dataclasses import dataclass

from .config import DIRECTIONS

PREFERRED_CHANNELS = ["O1", "O2", "P7", "P8"]

# The OpenBCI dongle is an FTDI FT231X.
FTDI_VID = 0x0403
OPENBCI_PID = 0x6015


class BoardError(RuntimeError):
    """Board could not be opened; the message is meant for the operator."""


@dataclass
class OpenBoard:
    board: object          # brainflow BoardShim or SimSSVEPBoard
    fs: int
    ch_rows: list
    ch_names: list
    device: str
    port: str | None


def _describe(p):
    vid = "%04X" % p.vid if p.vid is not None else "----"
    pid = "%04X" % p.pid if p.pid is not None else "----"
    return "%s (%s, VID:PID %s:%s)" % (p.device, p.description or "?", vid, pid)


def _is_bluetooth(p):
    text = " ".join(str(x or "") for x in (p.description, p.hwid, p.manufacturer)).lower()
    return "bluetooth" in text or "bthenum" in text


def find_openbci_port(ports=None) -> str:
    """Return the COM port of the single OpenBCI dongle, or raise BoardError.

    `ports` is a list of pyserial ListPortInfo-like objects (tests pass fakes);
    by default the live list. Only FTDI devices count; Bluetooth serial links
    (COM3/COM4 on this laptop) are never the headset.
    """
    if ports is None:
        from serial.tools import list_ports
        ports = list(list_ports.comports())
    ftdi = [p for p in ports if p.vid == FTDI_VID and not _is_bluetooth(p)]
    # Prefer the dongle's exact PID; another FTDI gadget may be plugged in too.
    exact = [p for p in ftdi if p.pid == OPENBCI_PID]
    matches = exact or ftdi
    seen = ", ".join(_describe(p) for p in ports) or "none"
    if not matches:
        raise BoardError("OpenBCI dongle not found (no FTDI serial port). Ports seen: %s. "
                         "Plug in the dongle (GPIO6 mode) or pass --port COMx." % seen)
    if len(matches) > 1:
        raise BoardError("Several possible OpenBCI dongles: %s. Pass --port COMx."
                         % ", ".join(_describe(p) for p in matches))
    return matches[0].device


def pick_channels(names, rows):
    """Prefer O1, O2, P7, P8 like ssvep_bci.main(); else the first four."""
    picks = [(n, r) for n, r in zip(names, rows) if n in PREFERRED_CHANNELS]
    if not picks:  # e.g. the synthetic board's generic names
        picks = list(zip(names, rows))[:4]
    return [n for n, _ in picks], [r for _, r in picks]


def open_board(settings) -> OpenBoard:
    """Open (prepare_session) the board for `settings.device`. Does not start the stream."""
    device = settings.device
    if device == "sim":
        from hub.sim.sim_board import SimSSVEPBoard
        board = SimSSVEPBoard([settings.freqs[d] for d in DIRECTIONS])
        board.prepare_session()
        names, rows = pick_channels(board.eeg_names, board.eeg_rows)
        return OpenBoard(board, board.sfreq, rows, names, device, None)

    if device not in ("cyton", "synthetic"):
        raise BoardError("unknown device %r (cyton, synthetic or sim)" % device)

    port = None
    if device == "cyton":
        port = settings.port or find_openbci_port()

    # Imported late: brainflow is slow to import and noisy about pkg_resources.
    from eegnb.devices.eeg import EEG
    from eegnb.devices.utils import EEG_CHANNELS, EEG_INDICES
    try:
        if device == "synthetic":
            eeg = EEG(device="synthetic")
        else:
            eeg = EEG(device="cyton", serial_port=port)  # never None: see module doc
    except Exception as exc:
        where = " on %s" % port if port else ""
        raise BoardError("could not open %s%s: %s: %s"
                         % (device, where, type(exc).__name__, exc)) from exc
    names, rows = pick_channels(EEG_CHANNELS[device], EEG_INDICES[device])
    return OpenBoard(eeg.board, int(eeg.sfreq), rows, names, device, port)
