"""
device.py
---------
ToolkitPy potentiostat connection and shared hardware-setup helpers used by
every run_*.py technique module.
"""

from __future__ import annotations

from contextlib import contextmanager


def connect_pstat(tkp, pstat_name: str | None):
    """Connect to a specific potentiostat section, or the first one found."""
    if pstat_name:
        return tkp.Pstat(pstat_name)

    sections = tkp.enum_sections()
    if not sections:
        raise RuntimeError("No Gamry potentiostat found by ToolkitPy enum_sections().")
    return tkp.Pstat(sections[0])


def resolve_versus_eoc(value_v: float, versus_eoc: bool, e_ocp: float) -> float:
    """Resolve a sequence-file potential that may be specified relative to Eoc."""
    return e_ocp + value_v if versus_eoc else value_v


def initialize_pstat_for_ramp(pstat) -> None:
    """Shared hardware settings for the DC ramp techniques (LPR, CPP),
    matching RDE/webui/gamry_worker/run_lsv.py and run_cv.py."""
    import toolkitpy as tkp

    pstat.set_ach_select(tkp.ACHSELECT_GND)
    pstat.set_ie_stability(tkp.STABILITY_NORM)
    pstat.set_ca_speed(tkp.CASPEED_NORM)
    pstat.set_ground(tkp.FLOAT)
    pstat.set_ich_range(3.0)
    pstat.set_ich_range_mode(False)
    pstat.set_ich_offset_enable(False)
    pstat.set_vch_range(10.0)
    pstat.set_vch_range_mode(True)
    pstat.set_vch_offset_enable(False)
    pstat.set_ach_range(3.0)
    pstat.set_ie_range_lower_limit(0)
    pstat.set_pos_feed_enable(False)
    pstat.set_analog_out(0.0)
    pstat.set_voltage(0.0)
    pstat.set_pos_feed_resistance(0.0)


def check_scan_resolution(pstat, voltage_list: list[float], scan_rate_v_s: float, sample_time_s: float) -> None:
    """Validate that a ramp's scan_rate/sample_time combination produces a DAC
    step size the connected instrument can actually resolve, raising
    ValueError if not. Without this, a scan_rate too slow for its
    sample_time silently repeats the same DAC code across several samples
    instead of stepping smoothly -- Gamry's own ToolkitPy example scripts
    (Experiment.check_scan_res) run this before every ramp for that reason.

    The step-size limit depends on the voltage window being scanned
    (window = (max(voltage_list) - min(voltage_list)) / 2) and whether the
    instrument has the UCB (higher-resolution DAC) option.
    """
    voltage_window = (max(voltage_list) - min(voltage_list)) / 2
    has_ucb = bool(pstat.has("UCB"))

    if voltage_window < 0.4:
        step_size_limit = 7.8125e-7 if has_ucb else 12.5e-6
    elif voltage_window < 1.6:
        step_size_limit = 3.125e-6 if has_ucb else 50.0e-6
    elif voltage_window < 6.4:
        step_size_limit = 12.5e-6 if has_ucb else 200.0e-6
    else:
        raise ValueError(
            f"Voltage window ({voltage_window:.3f} V, computed as "
            "(max-min)/2 over the scan's voltages) exceeds the 6.4 V limit "
            "for a single scan."
        )

    step_size = sample_time_s * abs(scan_rate_v_s)
    if step_size < step_size_limit:
        raise ValueError(
            f"Scan step size ({step_size:.3g} V, from sample_time_s x "
            f"scan_rate_v_s) is below the {step_size_limit:.3g} V DAC "
            f"resolution limit for a {voltage_window:.3f} V window. Increase "
            "scan_rate_v_s and/or sample_time_s, or narrow the voltage window."
        )


def safe_cell_off(tkp, pstat) -> None:
    """Turn the cell off if the pstat handle is still valid, swallowing any
    error during teardown -- the guarded set_cell(False) duplicated in every
    technique module's cleanup path."""
    try:
        if tkp.pstat_is_valid(pstat):
            pstat.set_cell(False)
    except Exception:
        pass


def cleanup_ramp_curve(tkp, pstat, curve, signal=None) -> None:
    """Stop/free a run(True)-driven curve (OcvCurve/RcvCurve) and turn the
    cell off, swallowing any error along the way -- the try/except/finally
    teardown duplicated across run_ocp.py, run_lpr.py, and run_cpp.py.
    Call from within a `finally:` block after the curve has been created."""
    try:
        if curve.running():
            curve.stop()
    except Exception:
        pass
    safe_cell_off(tkp, pstat)
    try:
        curve.free()
    except Exception:
        pass
    if signal is not None:
        del signal
    del curve


@contextmanager
def open_session(pstat_name: str | None):
    """Initializes ToolkitPy and connects to a potentiostat, yielding
    (tkp, pstat). Guarantees cell-off and teardown on exit regardless of
    what the caller does with the pstat inside -- the device lifecycle any
    orchestration needs, independent of which techniques it runs or in
    what order."""
    import toolkitpy as tkp

    tkp.toolkitpy_init("potentiostat_main.py")
    pstat = None
    try:
        pstat = connect_pstat(tkp, pstat_name)
        if hasattr(pstat, "open"):
            pstat.open()
        yield tkp, pstat
    finally:
        if pstat is not None:
            safe_cell_off(tkp, pstat)
            del pstat

        try:
            tkp.toolkitpy_close()
        except Exception:
            pass


def initialize_pstat_for_eis(pstat) -> None:
    """Shared hardware settings for EIS, matching run_eis.py in RDE."""
    import toolkitpy as tkp

    pstat.set_cell(False)
    pstat.set_ach_select(tkp.ACHSELECT_GND)
    pstat.set_ie_stability(tkp.STABILITY_FAST)
    pstat.set_ca_speed(tkp.CASPEED_NORM)
    pstat.set_ground(tkp.FLOAT)
    pstat.set_i_convention(tkp.ICONVENTION.ANODIC)
    pstat.set_ich_range(3.0)
    pstat.set_ich_range_mode(False)
    pstat.set_ich_filter(3.0)
    pstat.set_vch_range(3.0)
    pstat.set_vch_range_mode(False)
    pstat.set_vch_filter(2.50)
    pstat.set_ich_offset_enable(True)
    pstat.set_vch_offset_enable(True)
    pstat.set_ach_range(3.0)
    pstat.set_ie_range(0.03)
    pstat.set_ie_range_mode(False)
    pstat.set_ie_range_lower_limit(0)
    pstat.set_analog_out(0.0)
    pstat.set_pos_feed_enable(False)
    pstat.set_irupt_mode(tkp.IRUPTOFF)
