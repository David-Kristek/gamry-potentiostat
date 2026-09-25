"""Potentiostat measurement library: connects to a Gamry potentiostat via
ToolkitPy and runs the OCP -> EIS -> LPR -> CPP sequence. It only does the
measurement work that runs under the Gamry 32-bit Python -- filling in the
run parameters and launching a sequence is shown in ``examples/``:
either directly under the Gamry Python (``core.sequence.execute_sequence``,
no subprocess) or from any interpreter via
``gamry_potentiostat.runner.run_sequence``, which spawns the Gamry Python
itself as an IPC worker -- no separate launcher process needed.

Building blocks are grouped by concern, each importable on its own:
``potentiostat.core`` (hardware I/O, technique runners, the sequence driver and
its event/abort plumbing -- the part that must run under the Gamry 32-bit
Python 3.7), ``potentiostat.gamry_potentiostat`` (host-side: resolve/validate
the Gamry env, spawn it as an IPC worker), ``potentiostat.utils``
(progress/throttle helpers, technique-key math, console logging),
``potentiostat.parsing`` (config models, sequence files),
``potentiostat.plotting`` (live dashboard, post-run PNG writer). The generic,
Gamry-agnostic IPC transport this runs over -- Supervisor/Worker,
AbortSignal, submit -- is the separate ``pyproc-bridge`` package (an
external dependency, not part of this package).
"""

from potentiostat.parsing.sequence_config import SequenceConfig, OCPConfig, EISConfig, LPRConfig, CPPConfig
from potentiostat.core.techniques import SequenceResults
from potentiostat.core.sequence.sequence import (
    ExecuteSequenceConfig,
    execute_sequence,
    execute_sequence_sync,
)

__all__ = [
    "SequenceConfig",
    "OCPConfig",
    "EISConfig",
    "LPRConfig",
    "CPPConfig",
    "ExecuteSequenceConfig",
    "SequenceResults",
    "execute_sequence",
    "execute_sequence_sync",
]
