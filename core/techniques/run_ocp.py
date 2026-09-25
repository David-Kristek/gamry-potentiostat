"""
run_ocp.py
----------
Open-Circuit Potential: hold the cell at rest and log Eoc versus time. The
final reading is the Eoc every later technique references.
"""

from __future__ import annotations

import time
from typing import Optional

from potentiostat.core.hardware.device import cleanup_ramp_curve
from potentiostat.core.techniques.technique import (
    Technique,
    TechniqueContext,
    TechniqueResult,
)
from potentiostat.parsing.sequence_config import OCPConfig
from potentiostat.plotting.technique_plots import OCPPlotter


class OCP(Technique[OCPConfig]):
    name = "ocp"
    col_mapping = {"time": "Time (s)", "vf": "OCP (V)"}
    plotter = OCPPlotter

    def _initialize(self, ctx: TechniqueContext[OCPConfig]) -> None:
        ctx.pstat.set_ctrl_mode(ctx.tkp.PSTATMODE)

    @staticmethod
    def estimated_total_duration_s(cfg: OCPConfig) -> Optional[float]:
        return cfg.total_time_s

    def _measure(self, ctx: TechniqueContext[OCPConfig]) -> tuple[TechniqueResult, float]:
        cfg = ctx.cfg
        max_size = max(1000, (self.estimated_total_points(cfg) or 0) + 1000)

        curve = ctx.tkp.OcvCurve(ctx.pstat, max_size)
        signal = None
        try:
            signal = ctx.pstat.signal_const_new(0.0, cfg.total_time_s, cfg.sample_time_s, ctx.tkp.PSTATMODE)
            ctx.pstat.set_cell(False)
            ctx.pstat.set_signal_const(signal)
            ctx.pstat.init_signal()

            curve.run(True)
            while ctx.tkp.pstat_is_valid(ctx.pstat) and curve.running():
                time.sleep(max(0.01, min(cfg.sample_time_s, 0.25)))
                ctx.raise_if_aborted()
                ctx.emitter.emit_progress(curve.acq_data())

            raw = curve.acq_data()
            ctx.tkp.print_default_dta_file(curve, ctx.pstat, ctx.dta_path, "CORPOT")
        finally:
            cleanup_ramp_curve(ctx.tkp, ctx.pstat, curve, signal)

        final_e_ocp = float(raw[-1]["vf"]) if (raw is not None and len(raw)) else 0.0
        return {"data": raw, "dta_path": ctx.dta_path, "csv_path": ctx.csv_path}, final_e_ocp
