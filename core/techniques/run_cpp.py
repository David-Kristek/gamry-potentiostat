"""
run_cpp.py
----------
Cyclic Potentiodynamic Polarization (CPP): a wide anodic sweep past Eoc to
find the breakdown potential, reversing either at a fixed apex or (per
ASTM G61) as soon as the anodic current density crosses i_limit_ma_cm2. See
theory/Corrosion-Measurement-Methods-Overview.md for the electrochemistry
behind this technique.
"""

from __future__ import annotations

import time
from typing import Optional

import numpy as np
import pandas as pd

from potentiostat.parsing.sequence_config import CPPConfig
from potentiostat.core.hardware.device import (
    check_scan_resolution,
    cleanup_ramp_curve,
    initialize_pstat_for_ramp,
    resolve_versus_eoc,
    safe_cell_off,
)
from potentiostat.core.techniques.technique import Technique, TechniqueContext, TechniqueData, TechniqueResult
from potentiostat.plotting.technique_plots import CPPPlotter


def _finish_leg(curve, signal) -> None:
    """Stop/free one leg's curve without touching the cell -- the cell must
    stay energized across the forward->reverse transition so there's no
    open-circuit gap between the two ramps."""
    try:
        if curve.running():
            curve.stop()
    except Exception:
        pass
    try:
        curve.free()
    except Exception:
        pass
    if signal is not None:
        del signal


def _concat_leg_data(raw_fwd, raw_rev, sample_time: float):
    """Stitch the forward and reverse legs' acq_data() arrays into one
    continuous table, offsetting the reverse leg's point/time columns so
    they continue from where the forward leg left off (each leg is a
    separate RcvCurve, so both columns restart from 0 on their own)."""
    if len(raw_rev) == 0:
        return raw_fwd
    if len(raw_fwd) == 0:
        return raw_rev
    raw_rev = raw_rev.copy()
    raw_rev["point"] += raw_fwd["point"][-1] + 1
    raw_rev["time"] += raw_fwd["time"][-1] + sample_time
    return np.concatenate([raw_fwd, raw_rev])


class _CombinedCurveView:
    """Duck-typed stand-in for RcvCurve so tkp.print_cyclic_polarization_dta_file
    (which only ever calls curve.data_table() -> curve.acq_data() /
    curve.datafile_info()) can write one continuous CURVE table from the
    forward+reverse legs' combined data, reusing Gamry's own table-writing
    code instead of re-implementing the .DTA format."""

    def __init__(self, tkp, data):
        self._tkp = tkp
        self._data = data

    def acq_data(self):
        return self._data

    def datafile_info(self):
        return self._tkp.RcvCurve.datafile_info(self)

    def data_table(self, tag="CURVE"):
        return self._tkp.RcvCurve.data_table(self, tag)


class CPP(Technique[CPPConfig]):
    name = "cpp"
    col_mapping = {"vf": "Potential_V", "im": "Current_A"}
    plotter = CPPPlotter

    def _initialize(self, ctx: TechniqueContext[CPPConfig]) -> None:
        initialize_pstat_for_ramp(ctx.pstat)
        ctx.pstat.set_ctrl_mode(ctx.tkp.PSTATMODE)

    @staticmethod
    def _leg_durations_s(cfg: CPPConfig) -> tuple[float, float] | None:
        # v_init_v/v_apex_v/v_final_v used un-resolved -- see the matching note in
        # run_lpr.py's estimated_total_duration_s. Assumes the nominal
        # v_init->v_apex->v_final path; an ASTM G61 current-triggered reversal
        # (i_limit_ma_cm2 > 0) can cut the forward leg short, so this is an upper bound
        # in that case, not an exact estimate.
        if cfg.scan_fwd_v_s == 0 or cfg.scan_rev_v_s == 0:
            return None
        fwd = abs(cfg.v_apex_v - cfg.v_init_v) / abs(cfg.scan_fwd_v_s)
        rev = abs(cfg.v_final_v - cfg.v_apex_v) / abs(cfg.scan_rev_v_s)
        return fwd, rev

    @staticmethod
    def estimated_total_duration_s(cfg: CPPConfig) -> Optional[float]:
        durations = CPP._leg_durations_s(cfg)
        return sum(durations) if durations is not None else None

    def _measure(self, ctx: TechniqueContext[CPPConfig]) -> tuple[TechniqueResult, float]:
        if str(ctx.cfg.signal_mode).lower() == "single_signal":
            return self._measure_single_signal(ctx)
        return self._measure_two_leg(ctx)

    def _measure_two_leg(self, ctx: TechniqueContext[CPPConfig]) -> tuple[TechniqueResult, float]:
        cfg = ctx.cfg
        v_init = resolve_versus_eoc(cfg.v_init_v, cfg.v_init_versus_eoc, ctx.e_ocp)
        v_apex = resolve_versus_eoc(cfg.v_apex_v, cfg.v_apex_versus_eoc, ctx.e_ocp)
        v_final = resolve_versus_eoc(cfg.v_final_v, cfg.v_final_versus_eoc, ctx.e_ocp)
        sample_time = max(cfg.sample_time_s, 0.1)
        area_cm2 = cfg.area_cm2 or 1.0
        i_limit_ma_cm2 = cfg.i_limit_ma_cm2 or 0.0

        if cfg.scan_fwd_v_s == 0 or cfg.scan_rev_v_s == 0:
            raise ValueError("CPP scan_fwd_v_s/scan_rev_v_s must be nonzero.")

        # Worst case (slowest) scan rate sets the tightest DAC step-size floor.
        check_scan_resolution(
            ctx.pstat, [v_init, v_apex, v_final], min(abs(cfg.scan_fwd_v_s), abs(cfg.scan_rev_v_s)), sample_time
        )

        scan1_time, scanf_time = self._leg_durations_s(cfg)
        max_size_fwd = max(1000, int(scan1_time / sample_time) + 1000)
        max_size_rev = max(1000, int(scanf_time / sample_time) + 1000)

        curve_fwd = ctx.tkp.RcvCurve(ctx.pstat, max_size_fwd)

        # ASTM G61-style reversal: if a current limit is configured, the forward
        # leg's built-in StopAt ends that ramp (RcvCurve.running() goes False)
        # the moment anodic current density crosses i_limit_ma_cm2, instead of
        # running all the way to v_apex.
        if i_limit_ma_cm2 > 0:
            i_limit_amps = i_limit_ma_cm2 * area_cm2 / 1000.0
            curve_fwd.set_stop_i_max(True, i_limit_amps)

        signal = None
        curve_rev = None
        stopped = False

        try:
            # Forward (anodic) leg: v_init -> v_apex.
            signal = ctx.pstat.signal_ramp_new(v_init, v_apex, cfg.scan_fwd_v_s, sample_time, ctx.tkp.PSTATMODE)
            ctx.pstat.set_signal_ramp(signal)
            ctx.pstat.init_signal()
            ctx.pstat.set_cell(True)
            time.sleep(0.010)

            curve_fwd.run(True)
            while ctx.tkp.pstat_is_valid(ctx.pstat) and curve_fwd.running():
                time.sleep(max(0.01, min(sample_time, 0.25)))
                if ctx.abort:
                    stopped = True
                    break
                ctx.emitter.emit_progress(curve_fwd.acq_data())

            raw_fwd = curve_fwd.acq_data()
            _finish_leg(curve_fwd, signal)
            signal = None

            # Reverse (cathodic) leg: continue from wherever the forward leg
            # actually ended (v_apex, or an earlier current-triggered reversal)
            # down to v_final. The cell is never turned off between legs, so
            # there's no open-circuit gap at the transition -- unless a stop was
            # requested mid-forward-leg, in which case there's no point starting
            # the reverse leg at all and the cell should come off right away
            # instead of staying energized while it's written out.
            if not stopped:
                v_reversal = float(raw_fwd["vf"][-1]) if len(raw_fwd) else v_apex
                curve_rev = ctx.tkp.RcvCurve(ctx.pstat, max_size_rev)
                signal = ctx.pstat.signal_ramp_new(
                    v_reversal, v_final, cfg.scan_rev_v_s, sample_time, ctx.tkp.PSTATMODE
                )
                ctx.pstat.set_signal_ramp(signal)
                ctx.pstat.init_signal()

                curve_rev.run(True)
                while ctx.tkp.pstat_is_valid(ctx.pstat) and curve_rev.running():
                    time.sleep(max(0.01, min(sample_time, 0.25)))
                    if ctx.abort:
                        stopped = True
                        break
                    ctx.emitter.emit_progress(_concat_leg_data(raw_fwd, curve_rev.acq_data(), sample_time))

            if ctx.tkp.pstat_is_valid(ctx.pstat):
                ctx.pstat.set_cell(False)

            raw_rev = curve_rev.acq_data() if curve_rev is not None else raw_fwd[:0]
            raw = _concat_leg_data(raw_fwd, raw_rev, sample_time)

            ctx.tkp.print_cyclic_polarization_dta_file(
                _CombinedCurveView(ctx.tkp, raw),
                ctx.pstat,
                ctx.dta_path,
                v_init,
                v_apex,
                v_final,
                cfg.scan_fwd_v_s,
                cfg.scan_rev_v_s,
                sample_time,
                area_cm2,
                cfg.density_g_cm3,
                cfg.equiv_weight,
                eoc=ctx.e_ocp,
                experiment_tag="CYCPOL",
            )
            legs = ["CURVE1"] * len(raw_fwd) + ["CURVE2"] * len(raw_rev)
        finally:
            safe_cell_off(ctx.tkp, ctx.pstat)
            _finish_leg(curve_fwd, signal if curve_rev is None else None)
            del curve_fwd
            if curve_rev is not None:
                _finish_leg(curve_rev, signal)
                del curve_rev

        return {"data": raw, "dta_path": ctx.dta_path, "csv_path": ctx.csv_path, "legs": legs}, ctx.e_ocp

    def _measure_single_signal(self, ctx: TechniqueContext[CPPConfig]) -> tuple[TechniqueResult, float]:
        """CPP as one continuous signal_r_up_dn_new sweep (v_init -> v_apex -> v_final),
        the same pattern Gamry_ToolkitPy_Docs/scripts_examples/CV.py uses for cyclic
        voltammetry, instead of two stitched signal_ramp_new legs.

        Cannot do the ASTM G61 current-triggered reversal that the two-leg path
        supports: per ToolkitPy's StopAt semantics, a threshold trip on a
        multi-vertex signal skips to the next pre-programmed segment rather than
        reversing from the actual crossing potential, so the reverse leg would jump
        from the nominal v_apex instead of from wherever the current limit was really
        crossed. Only use this for a fixed-apex scan (i_limit_ma_cm2 == 0); it raises
        otherwise.
        """
        cfg = ctx.cfg
        v_init = resolve_versus_eoc(cfg.v_init_v, cfg.v_init_versus_eoc, ctx.e_ocp)
        v_apex = resolve_versus_eoc(cfg.v_apex_v, cfg.v_apex_versus_eoc, ctx.e_ocp)
        v_final = resolve_versus_eoc(cfg.v_final_v, cfg.v_final_versus_eoc, ctx.e_ocp)
        sample_time = max(cfg.sample_time_s, 0.1)
        area_cm2 = cfg.area_cm2 or 1.0
        i_limit_ma_cm2 = cfg.i_limit_ma_cm2 or 0.0

        if i_limit_ma_cm2 > 0:
            raise ValueError(
                "CPP single_signal mode cannot do ASTM G61 current-triggered reversal -- "
                "set i_limit_ma_cm2 to 0 for a fixed-apex scan, or use two_leg mode instead."
            )

        if cfg.scan_fwd_v_s == 0 or cfg.scan_rev_v_s == 0:
            raise ValueError("CPP scan_fwd_v_s/scan_rev_v_s must be nonzero.")

        check_scan_resolution(
            ctx.pstat, [v_init, v_apex, v_final], min(abs(cfg.scan_fwd_v_s), abs(cfg.scan_rev_v_s)), sample_time
        )

        estimated_time = self.estimated_total_duration_s(cfg)
        max_size = max(1000, int(estimated_time / sample_time) + 1000)

        curve = ctx.tkp.RcvCurve(ctx.pstat, max_size)
        signal = None

        try:
            # signal_r_up_dn_new needs 4 vertices (init, apex1, apex2, final) for its
            # up-down-up shape, but a 2-leg CPP only has 2 real legs (v_init -> v_apex
            # -> v_final). ToolkitPy rejects a repeated *middle* vertex (apex1 ==
            # apex2, i.e. putting the real v_apex/v_final split there) outright with
            # ERRAPP_PC5_SIGNAL_INVALID -- confirmed against real hardware -- but
            # tolerates a repeated *trailing* one, so the real 2-leg shape goes in
            # slots 1-2 (apex1=v_apex, apex2=v_final) and slot 3 is a zero-distance,
            # zero-rate placeholder that never actually moves the DAC.
            signal = ctx.pstat.signal_r_up_dn_new(
                [v_init, v_apex, v_final, v_final],
                [cfg.scan_fwd_v_s, cfg.scan_rev_v_s, 0.0],
                [0.0, 0.0, 0.0],
                sample_time,
                1,
                ctx.tkp.PSTATMODE,
            )
            ctx.pstat.set_signal_r_up_dn(signal)
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
            ctx.tkp.print_cyclic_polarization_dta_file(
                curve,
                ctx.pstat,
                ctx.dta_path,
                v_init,
                v_apex,
                v_final,
                cfg.scan_fwd_v_s,
                cfg.scan_rev_v_s,
                sample_time,
                area_cm2,
                cfg.density_g_cm3,
                cfg.equiv_weight,
                eoc=ctx.e_ocp,
                experiment_tag="CYCPOL",
            )
        finally:
            cleanup_ramp_curve(ctx.tkp, ctx.pstat, curve, signal)

        return {"data": raw, "dta_path": ctx.dta_path, "csv_path": ctx.csv_path}, ctx.e_ocp

    def to_dataframe(self, data: TechniqueData, legs: list[str] | None = None, **kwargs) -> pd.DataFrame:
        """`legs` tags each row with which ramp leg it came from ("CURVE1"
        forward / "CURVE2" reverse, matching print_cyclic_polarization_dta_file's
        table tags) so CPPPlotter can color the anodic/cathodic legs separately;
        omit it (single continuous sweep) for one untagged leg."""
        if legs is None:
            legs = ["CURVE"] * len(data)
        return pd.DataFrame({"Potential_V": data["vf"], "Current_A": data["im"], "Leg": legs})

    def _write_csv(self, path: str, result: TechniqueResult) -> None:
        self.to_dataframe(result["data"], legs=result.get("legs")).to_csv(path, index=False)
