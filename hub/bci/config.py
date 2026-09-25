"""Engine settings: the knobs the CLI sets and the dashboard can tune live."""
from dataclasses import dataclass, field

# Target ids, in the fixed order used everywhere (protocol.md).
DIRECTIONS = ["up", "down", "left", "right"]


@dataclass
class EngineSettings:
    device: str = "cyton"            # "cyton" | "synthetic" | "sim"
    port: str | None = None          # None -> auto-detect the OpenBCI dongle
    freqs: dict[str, float] = field(default_factory=lambda: {
        "up": 11.0, "down": 14.0, "left": 17.0, "right": 20.0})
    window_s: float = 3.0
    margin: float = 0.08
    dwell: int = 2                   # consecutive decodes before a direction activates
    speed: float = 0.3               # normalised, 0..1
    interval_s: float = 0.25         # decode period
    model_path: str | None = None    # optional ssvep_calibrate.py .npz
    mode: str = "trca_cca"           # scorer used with model_path
