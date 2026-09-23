"""Custom sequence logic: skip `execute_sequence`'s fixed ocp-first loop
(core/sequence.py::execute_sequence_sync) and call technique runners
directly, branching on results as you go -- for when "OCP first, then the
rest in list order" doesn't fit: skipping a technique based on what OCP
measured, repeating one, or running an order the built-in loop can't express.

Run under the Gamry 32-bit Python:

    "C:/.../Gamry Instruments/.../python.exe" -m examples.custom_sequence

See examples/single_technique.py for the simplest possible one-technique run,
and examples/run_measurement.py for the built-in full-sequence orchestrator
this bypasses.
"""

from __future__ import annotations

import os

from potentiostat.core.hardware.device import open_session
from potentiostat.core.techniques.technique import Technique, TechniqueContext
from potentiostat.core.workflow.emitter import WorkflowEvent
from pyproc_bridge import AbortSignal
from potentiostat.parsing.sequence_config import SequenceConfig

OUT_DIR = "./run_output"


def on_event(event: WorkflowEvent) -> None:
    print(f"[{event.kind}] {event.key}")


def run_technique(
    name: str, *, tkp, pstat, cfg: SequenceConfig, e_ocp: float, abort: AbortSignal
) -> float:
    """Build the context and run one technique, returning its new Eoc --
    exactly what execute_sequence_sync's loop body does, pulled out here so
    custom control flow can call it as many or as few times as it wants."""
    ctx = TechniqueContext.from_sequence(
        key=name,
        tkp=tkp,
        pstat=pstat,
        config=cfg,
        technique_name=name,
        e_ocp=e_ocp,
        outdir=OUT_DIR,
        on_event=on_event,
        abort=abort,
    )
    _result, new_e_ocp = Technique.get(name)().run(ctx)
    return new_e_ocp


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    cfg = SequenceConfig()
    abort = AbortSignal()

    with open_session(None) as (tkp, pstat):
        e_ocp = run_technique("ocp", tkp=tkp, pstat=pstat, cfg=cfg, e_ocp=0.0, abort=abort)
        print(f"OCP settled at {e_ocp:+.4f} V")

        # Custom branch: a resting potential outside the "healthy" window
        # rechecks OCP instead of running EIS/LPR/CPP against a probably-bad
        # reading -- execute_sequence_sync has no equivalent, it always just
        # runs the next technique in the list.
        if abs(e_ocp) > 0.5:
            print("Eoc looks off -- rechecking OCP instead of continuing")
            e_ocp = run_technique("ocp", tkp=tkp, pstat=pstat, cfg=cfg, e_ocp=e_ocp, abort=abort)
        else:
            for name in ("eis", "lpr", "cpp"):
                if abort.aborted:
                    break
                e_ocp = run_technique(name, tkp=tkp, pstat=pstat, cfg=cfg, e_ocp=e_ocp, abort=abort)

    print("done")


if __name__ == "__main__":
    main()
