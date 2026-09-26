"""BCI engine: board, decoder wiring and the safety arbiter (Phase 1B).

`control/` is put on sys.path here so `import ssvep_bci` works from the hub.
Importing ssvep_bci does not load psychopy (only its main() does).
"""
import os
import sys

_CONTROL = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "control"))
if _CONTROL not in sys.path:
    sys.path.insert(0, _CONTROL)

from .config import DIRECTIONS, EngineSettings  # noqa: E402

__all__ = ["DIRECTIONS", "EngineSettings", "BciEngine"]


def __getattr__(name):
    # Lazy, so `from hub.bci import EngineSettings` doesn't pull in brainflow.
    if name == "BciEngine":
        from .engine import BciEngine
        return BciEngine
    raise AttributeError(name)
