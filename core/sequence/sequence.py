"""
sequence.py
"""

from __future__ import annotations

from concurrent.futures import Future
from typing import Callable, List, Optional

from potentiostat.parsing.sequence_config import SequenceConfig
from potentiostat.core.hardware import device_validator
from pyproc_bridge import AbortSignal, submit
from potentiostat.core.workflow.emitter import WorkflowEvent
from potentiostat.core.hardware.device import open_session
from potentiostat.core.techniques.technique import (
    Technique,
    TechniqueContext,
    TechniqueOutcome,
    SequenceResults,
)
from potentiostat.utils.technique_keys import base_technique
from pydantic import BaseModel, Field


class ExecuteSequenceConfig(BaseModel):
    """Configuration for executing a sequence of techniques."""

    # List[...]/Optional[...], not list[...]/X | None: pydantic evaluates
    # these eagerly even under `from __future__ import annotations`, and the
    # Gamry Python is 3.7 (no PEP 585/604 at runtime).
    technique_keys: List[str]
    outdir: str
    config: SequenceConfig = Field(default_factory=SequenceConfig)
    pstat_name: Optional[str] = None


def execute_sequence_sync(
    cfg: ExecuteSequenceConfig,
    *,
    on_event: Callable[[WorkflowEvent], None] = lambda _event: None,
    abort: AbortSignal,
) -> SequenceResults:
    """The actual (synchronous, blocking) run -- see ``execute_sequence``."""
    techniques = [base_technique(key) for key in cfg.technique_keys]

    if techniques and techniques[0] != "ocp":
        raise ValueError("Technique sequence must start with 'ocp'.")

    if len(set(cfg.technique_keys)) != len(cfg.technique_keys):
        raise ValueError("Technique keys must be unique.")

    abort.raise_if_aborted()  # don't touch hardware if already cancelled

    e_ocp = 0.0
    outcomes: dict[str, TechniqueOutcome] = {}

    with open_session(cfg.pstat_name) as (tkp, pstat):
        device_validator.validate_device_parameters(pstat, cfg.config, raise_on_error=True)

        for name, key in zip(techniques, cfg.technique_keys):
            abort.raise_if_aborted()

            ctx = TechniqueContext.from_sequence(
                key=key,
                tkp=tkp,
                pstat=pstat,
                config=cfg.config,
                technique_name=name,
                e_ocp=e_ocp,
                outdir=cfg.outdir,
                on_event=on_event,
                abort=abort,
            )
            result, e_ocp = Technique.get(name)().run(ctx)
            outcomes[key] = TechniqueOutcome(
                dta_path=result["dta_path"],
                csv_path=result["csv_path"],
                legs=result.get("legs"),
            )
    return SequenceResults(outcomes)


def execute_sequence(
    cfg: ExecuteSequenceConfig,
    *,
    on_event: Callable[[WorkflowEvent], None] = lambda _event: None,
    abort: AbortSignal | None = None,
) -> Future[SequenceResults]:
    """Run the sequence on a side thread, returning a ``Future[SequenceResults]``
    immediately. For a synchronous call, ``execute_sequence(...).result()``."""
    abort = abort or AbortSignal()
    return submit(
        lambda: execute_sequence_sync(cfg, on_event=on_event, abort=abort),
        thread_name="execute-sequence",
    )
