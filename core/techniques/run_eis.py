"""
run_eis.py
----------
Electrochemical Impedance Spectroscopy (EIS): a log-spaced frequency sweep
under a small AC perturbation, biased at (or near) Eoc. See
theory/Corrosion-Measurement-Methods-Overview.md for the electrochemistry
behind this technique.
"""

from __future__ import annotations

import math
import time
from typing import Optional

import pandas as pd

from potentiostat.parsing.sequence_config import EISConfig
from potentiostat.core.hardware.device import initialize_pstat_for_eis, resolve_versus_eoc, safe_cell_off
from potentiostat.core.techniques.technique import Technique, TechniqueContext, TechniqueData, TechniqueResult
from potentiostat.plotting.technique_plots import EISPlotter


def _estimated_eis_points(initial_freq_hz: float, final_freq_hz: float, points_per_decade: float) -> int:
    """Pure-Python mirror of ToolkitPy's ReadZ.check_eis_points (see
    Gamry_ToolkitPy_Docs/scripts_examples/EIS.py) -- used for a pre-run estimate since the
    real check_eis_points() needs a live tkp/pstat handle that isn't available yet here."""
    init_log = abs(math.log10(initial_freq_hz)) == float(math.floor(abs(math.log10(initial_freq_hz))))
    final_log = abs(math.log10(final_freq_hz)) == float(math.floor(abs(math.log10(final_freq_hz))))
    factor = 0 if (init_log and final_log) else 1

    preround = 0.50 + abs(math.log10(final_freq_hz) - math.log10(initial_freq_hz)) * points_per_decade
    # Python's round() is banker's rounding; check_eis_points wants ordinary round-half-up.
    rounded = math.ceil(preround) if (preround % 1) >= 0.5 else round(preround, 0)
    return int(factor + rounded)


class EIS(Technique[EISConfig]):
    name = "eis"
    plotter = EISPlotter
    col_mapping = {
        "zreal": "ZRe (Ohm)",
        "zimag": "-ZIm (Ohm)",
        "zfreq": "Applied Frequency (Hz)",
        "zmod": "Z (Ohm)",
        "zphz": "Phase (degree)",
    }

    def _initialize(self, ctx: TechniqueContext[EISConfig]) -> None:
        initialize_pstat_for_eis(ctx.pstat)
        ctx.pstat.set_ctrl_mode(ctx.tkp.PSTATMODE)

    @staticmethod
    def estimated_total_points(cfg: EISConfig) -> Optional[int]:
        initial_freq = abs(cfg.initial_freq_hz)
        final_freq = abs(cfg.final_freq_hz)
        if initial_freq <= 0 or final_freq <= 0 or cfg.points_per_decade < 1:
            return None
        return _estimated_eis_points(initial_freq, final_freq, cfg.points_per_decade)

    @staticmethod
    def estimate_remaining_time(
        cfg: EISConfig, elapsed_s: float, points_collected: int, total_points: int
    ) -> Optional[float]:
        # Disabled: per-point time varies a lot across a log-frequency sweep (low freqs are
        # slow) and Gamry documents no timing model, so a linear extrapolation misleads.
        return None

    def _measure(self, ctx: TechniqueContext[EISConfig]) -> tuple[TechniqueResult, float]:
        cfg = ctx.cfg
        initial_freq = abs(cfg.initial_freq_hz)
        final_freq = abs(cfg.final_freq_hz)
        dc_voltage = resolve_versus_eoc(cfg.dc_voltage_v, cfg.dc_versus_eoc, ctx.e_ocp)
        estimated_z = abs(cfg.estimated_z_ohm)

        if cfg.points_per_decade < 1:
            raise ValueError("EIS points_per_decade must be at least 1.")

        freq_lim_lower = ctx.pstat.freq_limit_lower()
        freq_lim_upper = ctx.pstat.freq_limit_upper()
        initial_freq = min(max(initial_freq, freq_lim_lower), freq_lim_upper)
        final_freq = min(max(final_freq, freq_lim_lower), freq_lim_upper)

        ctx.pstat.set_voltage(dc_voltage)
        ctx.pstat.set_cell(True)
        time.sleep(1.0)

        dc_current = ctx.pstat.measure_i()
        ac_current_est = abs(cfg.ac_voltage_v) / estimated_z
        ie_range = ctx.pstat.test_ie_range(abs(dc_current) + 1.414 * abs(ac_current_est))
        ctx.pstat.set_ie_range(ie_range)

        readz = ctx.tkp.ReadZ(ctx.pstat)
        readz.set_gain(1.0)
        readz.set_inoise(0.0)
        readz.set_vnoise(0.0)
        readz.set_ienoise(0.0)
        readz.set_zmod(estimated_z)
        readz.set_vdc(dc_voltage)
        readz.set_speed(cfg.speed)
        readz.set_drift_cor(cfg.drift_correction)
        readz.set_idc(dc_current)

        log_increment = 1.0 / cfg.points_per_decade
        if initial_freq > final_freq:
            log_increment = -log_increment

        max_points = int(ctx.tkp.check_eis_points(initial_freq, final_freq, cfg.points_per_decade))
        zcurve = ctx.tkp.ZCurve(max_points)

        try:
            for point_idx in range(max_points):
                if not ctx.tkp.pstat_is_valid(ctx.pstat):
                    break

                freq = math.pow(10.0, math.log10(initial_freq) + point_idx * log_increment)
                temp = ctx.pstat.measure_temp()
                measured = readz.measure(freq, cfg.ac_voltage_v, dc_voltage)
                if not measured:
                    time.sleep(0.010)
                    continue

                zcurve.add_point(readz, temp)

                ctx.raise_if_aborted()
                ctx.emitter.emit_progress(zcurve.acq_data())
                time.sleep(0.010)

            ctx.tkp.print_default_dta_file(zcurve, ctx.pstat, ctx.dta_path, "EISPOT")
        finally:
            safe_cell_off(ctx.tkp, ctx.pstat)
            try:
                del readz
            except Exception:
                pass

        data = zcurve.acq_data()
        del zcurve

        return {"data": data, "dta_path": ctx.dta_path, "csv_path": ctx.csv_path}, ctx.e_ocp

    def to_dataframe(self, data: TechniqueData, **kwargs) -> pd.DataFrame:
        # Custom (not the col_mapping default): "-ZIm (Ohm)" is the negated field.
        return pd.DataFrame(
            {
                "Applied Frequency (Hz)": data["zfreq"],
                "Z (Ohm)": data["zmod"],
                "ZRe (Ohm)": data["zreal"],
                "-ZIm (Ohm)": -data["zimag"],
                "Phase (degree)": data["zphz"],
            }
        )
