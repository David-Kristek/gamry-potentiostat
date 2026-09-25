"""Add a new technique: subclass `Technique`, give it its own tiny Pydantic
config, and run it -- no changes to core/techniques/ or SequenceConfig needed
for an ad hoc/one-off technique like this one.

`Technique.__init_subclass__` auto-registers any subclass that sets a `name`
ClassVar just by being defined -- so `Technique.get("hold")` below works the
moment this module is imported, no explicit registration call needed.

To make a technique like this permanently selectable through
`execute_sequence`/`run_sequence`'s `technique_keys=[...]` list, the same way
"ocp"/"eis"/"lpr"/"cpp" are: move the class into its own
core/techniques/run_*.py, add its config as a field on `SequenceConfig`
(parsing/sequence_config.py) named exactly like the technique (`from_sequence`
looks it up via `getattr(config, technique_name)`), and import that module
from core/techniques/__init__.py so it registers on import.

Run under the Gamry 32-bit Python:

    "C:/.../Gamry Instruments/.../python.exe" -m examples.add_technique
"""

from __future__ import annotations

import os
import time
from functools import partial

from potentiostat.core.hardware.device import cleanup_ramp_curve, open_session
from potentiostat.core.techniques.technique import (
    Technique,
    TechniqueContext,
    TechniqueEmitter,
    TechniqueResult,
    TechniqueTime,
)
from potentiostat.parsing.sequence_config import GamryBaseConfig

OUT_DIR = "./run_output"


class HoldConfig(GamryBaseConfig):
    voltage_v: float = 0.1
    total_time_s: float = 30.0
    sample_time_s: float = 0.5


class Hold(Technique[HoldConfig]):
    """Potentiostatic hold at a fixed voltage -- almost identical to
    core/techniques/run_ocp.py's OCP, except the cell stays closed at a set
    voltage instead of open. Kept as the smallest possible diff from OCP so
    every piece a real technique needs stays visible: _initialize, _measure,
    a TechniqueResult, and the col_mapping to_dataframe()/write_csv() use."""

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
            ctx.pstat.set_cell(True)  # closed, unlike OCP -- that's the whole difference
            ctx.pstat.set_signal_const(signal)
            ctx.pstat.init_signal()

            curve.run(True)
            while ctx.tkp.pstat_is_valid(ctx.pstat) and curve.running():
                time.sleep(max(0.01, min(cfg.sample_time_s, 0.25)))
                ctx.raise_if_aborted()
                ctx.emitter.emit_progress(curve.acq_data())

            raw = curve.acq_data()
            # "CORPOT" is OCP's DTA-type tag, reused here for illustration --
            # check ToolkitPy's DTA-type table for the correct tag before
            # relying on this for a real chronoamperometry run.
            ctx.tkp.print_default_dta_file(curve, ctx.pstat, ctx.dta_path, "CORPOT")
        finally:
            cleanup_ramp_curve(ctx.tkp, ctx.pstat, curve, signal)

        final_v = float(raw[-1]["vf"]) if (raw is not None and len(raw)) else cfg.voltage_v
        return {"data": raw, "dta_path": ctx.dta_path, "csv_path": ctx.csv_path}, final_v


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)

    technique = Technique.get("hold")()
    cfg = HoldConfig(voltage_v=0.1, total_time_s=30.0)

    with open_session(None) as (tkp, pstat):
        # Built by hand rather than TechniqueContext.from_sequence(), since
        # "hold" isn't a field on SequenceConfig -- from_sequence() only
        # knows how to pull a technique's config off SequenceConfig by name.
        timer = TechniqueTime(
            estimator=partial(technique.estimate_remaining_time, cfg),
            total_points=technique.estimated_total_points(cfg) or 0,
        )
        ctx = TechniqueContext(
            key="hold",
            technique_name="hold",
            cfg=cfg,
            e_ocp=0.0,
            outdir=OUT_DIR,
            pstat=pstat,
            tkp=tkp,
            emitter=TechniqueEmitter(
                key="hold",
                technique_name="hold",
                on_event=lambda e: print(f"[{e.kind}] {e.key}"),
                time=timer,
                abort=None,
            ),
            abort=None,
        )
        result, final_v = technique.run(ctx)

    print(f"hold: final voltage = {final_v:+.4f} V -> {result['csv_path']}")


if __name__ == "__main__":
    main()
