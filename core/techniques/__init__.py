"""The Technique ABC, its name-keyed registry (Technique._registry, reached
via Technique.get / Technique.from_key), and the per-run context passed to
Technique.run()."""


# Imported for the side effect: defining each Technique subclass registers it
# on Technique, so the registry is populated wherever this package is imported.
from potentiostat.core.techniques import run_cpp, run_eis, run_lpr, run_ocp  # noqa: E402,F401
from potentiostat.core.techniques.technique import (  # noqa: E402
    SequenceResults,
    Technique,
    TechniqueContext,
    TechniqueData,
    TechniqueOutcome,
    TechniqueResult,
)

__all__ = [
    "SequenceResults",
    "Technique",
    "TechniqueContext",
    "TechniqueData",
    "TechniqueOutcome",
    "TechniqueResult",
]
