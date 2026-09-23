"""
run_lpr.py
----------
Linear Polarization Resistance (LPR): a narrow (mV-scale) potential ramp
centered on Eoc, used to derive the polarization resistance Rp. See
theory/Corrosion-Measurement-Methods-Overview.md and
theory/Electrochemistry-Equations-Reference.md for the electrochemistry
behind this technique.
"""

from __future__ import annotations

import time
from typing import Optional

from potentiostat.parsing import gamry_io
from potentiostat.parsing.sequence_config import LPRConfig
from potentiostat.core.hardware.device import (
    check_scan_resolution,
    cleanup_ramp_curve,
    initialize_pstat_for_ramp,
    resolve_versus_eoc,
)
from potentiostat.core.techniques.technique import Technique, TechniqueContext, TechniqueResult
from potentiostat.plotting.technique_plots import LPRPlotter


class LPR(Technique[LPRConfig]):
    name = "lpr"
    col_mapping = {"vf": "Potential (V)", "im": "Current (A)"}
    plotter = LPRPlotter

    def _initialize(self, ctx: TechniqueContext[LPRConfig]) -> None:
        initialize_pstat_for_ramp(ctx.pstat)
        ctx.pstat.set_ctrl_mode(ctx.tkp.PSTATMODE)

    @staticmethod
    def estimated_total_duration_s(cfg: LPRConfig) -> Optional[float]:
        # v_init_v/v_final_v used un-resolved: Eoc's offset cancels out of the difference
        # when both ends are versus_eoc (the default), and Eoc isn't known yet pre-run.
        if cfg.scan_rate_v_s == 0:
            return None
        return abs(cfg.v_final_v - cfg.v_init_v) / abs(cfg.scan_rate_v_s)

    def _measure(self, ctx: TechniqueContext[LPRConfig]) -> tuple[TechniqueResult, float]:
        cfg = ctx.cfg
        v_init = resolve_versus_eoc(cfg.v_init_v, cfg.v_init_versus_eoc, ctx.e_ocp)
        v_final = resolve_versus_eoc(cfg.v_final_v, cfg.v_final_versus_eoc, ctx.e_ocp)
        sample_time = max(cfg.sample_time_s, 0.1)
        area_cm2 = cfg.area_cm2 or 1.0

        if cfg.scan_rate_v_s == 0:
            raise ValueError("LPR scan_rate_v_s must not be zero.")

        check_scan_resolution(ctx.pstat, [v_init, v_final], cfg.scan_rate_v_s, sample_time)

        estimated_time = self.estimated_total_duration_s(cfg)
        max_size = max(1000, int(estimated_time / sample_time) + 1000)

        curve = ctx.tkp.RcvCurve(ctx.pstat, max_size)
        signal = None
        try:
            signal = ctx.pstat.signal_ramp_new(v_init, v_final, cfg.scan_rate_v_s, sample_time, ctx.tkp.PSTATMODE)
            ctx.pstat.set_signal_ramp(signal)
            ctx.pstat.init_signal()
            ctx.pstat.set_cell(True)
            time.sleep(0.010)

            curve.run(True)
            while ctx.tkp.pstat_is_valid(ctx.pstat) and curve.running():
                time.sleep(max(0.01, min(sample_time, 0.25)))
                if ctx.abort:
                    break
                ctx.emitter.emit_progress(curve.acq_data())

            if ctx.tkp.pstat_is_valid(ctx.pstat):
                ctx.pstat.set_cell(False)

            raw = curve.acq_data()
            gamry_io.write_polarization_resistance_dta_file(
                ctx.tkp,
                curve,
                ctx.pstat,
                ctx.dta_path,
                v_init,
                v_final,
                cfg.scan_rate_v_s,
                sample_time,
                area_cm2,
                cfg.density_g_cm3,
                cfg.equiv_weight,
                cfg.beta_a_v_dec,
                cfg.beta_c_v_dec,
            )
        finally:
            cleanup_ramp_curve(ctx.tkp, ctx.pstat, curve, signal)

        return {"data": raw, "dta_path": ctx.dta_path, "csv_path": ctx.csv_path}, ctx.e_ocp
