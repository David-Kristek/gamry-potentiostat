"""Add a new technique and run it in a sequence.

Defining `Hold` registers it on the Technique registry just by setting `name`;
giving it a config field on a local `SequenceConfig` subclass lets
`execute_sequence` pull its parameters up by name, exactly like the built-ins.
Nothing in core/techniques/ or the shared parsing/sequence_config.py changes.

To make a technique a permanent built-in instead: move the class into its own
core/techniques/run_*.py, add its config as a field on the shipped
`SequenceConfig`, and import that module from core/techniques/__init__.py so it
registers on import.

Run under the Gamry 32-bit Python:

    "C:/.../Gamry Instruments/.../python.exe" -m examples.add_technique
"""

from __future__ import annotations

import os
import time

from pydantic import Field
from pyproc_bridge import AbortError

from potentiostat import ExecuteSequenceConfig, SequenceConfig, execute_sequence
from potentiostat.core.hardware.device import cleanup_ramp_curve
from potentiostat.core.techniques.technique import Technique, TechniqueContext, TechniqueResult
from potentiostat.core.workflow.emitter import WorkflowEvent
from potentiostat.parsing.sequence_config import GamryBaseConfig

OUT_DIR = "./run_output"


class HoldConfig(GamryBaseConfig):
    voltage_v: float = 0.1
    total_time_s: float = 30.0
    sample_time_s: float = 0.5


class Hold(Technique[HoldConfig]):
    """Potentiostatic hold at a fixed voltage -- OCP with the cell closed.

    Kept as the smallest possible diff from core/techniques/run_ocp.py so every
    piece a technique needs stays visible: `_initialize`, `_measure`, a
    `TechniqueResult`, and the `col_mapping` that seeds the CSV columns.
    """

    name = "hold"
    col_mapping = {"time": "Time (s)", "vf": "Voltage (V)"}

    def _initialize(self, ctx: TechniqueContext[HoldConfig]) -> None:
        ctx.pstat.set_ctrl_mode(ctx.tkp.PSTATMODE)

    def _measure(self, ctx: TechniqueContext[HoldConfig]) -> tuple[TechniqueResult, float]:
        cfg = ctx.cfg
        max_size = max(1000, int(cfg.total_time_s / max(cfg.sample_time_s, 1e-6)) + 1000)

        curve = ctx.tkp.OcvCurve(ctx.pstat, max_size)
        signal = None
        try:
            signal = ctx.pstat.signal_const_new(cfg.voltage_v, cfg.total_time_s, cfg.sample_time_s, ctx.tkp.PSTATMODE)
            ctx.pstat.set_cell(True)  # closed, unlike OCP -- the whole difference
            ctx.pstat.set_signal_const(signal)
            ctx.pstat.init_signal()

            curve.run(True)
            while ctx.tkp.pstat_is_valid(ctx.pstat) and curve.running():
                time.sleep(max(0.01, min(cfg.sample_time_s, 0.25)))
                ctx.raise_if_aborted()
                ctx.emitter.emit_progress(curve.acq_data())

            raw = curve.acq_data()
            # "CORPOT" is OCP's DTA-type tag, reused for illustration -- check
            # ToolkitPy's DTA-type table before a real chronoamperometry run.
            ctx.tkp.print_default_dta_file(curve, ctx.pstat, ctx.dta_path, "CORPOT")
        finally:
            cleanup_ramp_curve(ctx.tkp, ctx.pstat, curve, signal)

        final_v = float(raw[-1]["vf"]) if (raw is not None and len(raw)) else cfg.voltage_v
        return {"data": raw, "dta_path": ctx.dta_path, "csv_path": ctx.csv_path}, final_v


class MySequenceConfig(SequenceConfig):
    """`SequenceConfig` plus the one-off "hold" technique (a local subclass, so
    the shared model that mirrors the .GSequence format stays untouched)."""

    hold: HoldConfig = Field(default_factory=HoldConfig)


def on_event(event: WorkflowEvent) -> None:
    print(f"[{event.kind}] {event.key}")


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)

    cfg = ExecuteSequenceConfig(
        technique_keys=["ocp", "hold", "eis"],  # any order, must start with "ocp"
        outdir=OUT_DIR,
        config=MySequenceConfig(hold=HoldConfig(voltage_v=0.1, total_time_s=30.0)),
    )

    future = execute_sequence(cfg, on_event=on_event)  # runs on a side thread
    try:
        results = future.result()
    except AbortError:
        print("run aborted")
    else:
        print("sequence complete:")
        for key in results:
            print(f"  {key}: {results[key].csv_path}")


if __name__ == "__main__":
    main()
