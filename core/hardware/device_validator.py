"""
device_validator.py
-------------------
Handles parameter validation for potentiostat hardware models (Gamry Reference 600+,
Interface 1000, Interface 5000, etc.).

Emits warnings or raises errors when requested parameters do not match or exceed
the physical capabilities of the connected potentiostat.
"""

import warnings
from typing import Dict, Any, List, Optional, Tuple
import math
import json

from potentiostat.parsing.sequence_config import SequenceConfig

# Known specifications for common Gamry potentiostat models
MODEL_SPECS: Dict[str, Dict[str, Any]] = {
    "REFERENCE 600+": {
        "name": "Gamry Reference 600+",
        "max_current_a": 0.600,       # ±600 mA
        "min_current_a": 60e-15,      # 60 fA resolution
        "max_voltage_v": 11.0,        # ±11 V compliance
        "freq_min_hz": 10e-6,         # 10 µHz
        "freq_max_hz": 5e6,           # 5 MHz
        "max_scan_rate_v_s": 100.0,   # 100 V/s
        "min_sample_period_s": 10e-6, # 10 µs
    },
    "REFERENCE 600": {
        "name": "Gamry Reference 600",
        "max_current_a": 0.600,
        "min_current_a": 60e-15,
        "max_voltage_v": 11.0,
        "freq_min_hz": 10e-6,
        "freq_max_hz": 1e6,           # 1 MHz
        "max_scan_rate_v_s": 100.0,
        "min_sample_period_s": 10e-6,
    },
    "INTERFACE 1000": {
        "name": "Gamry Interface 1000",
        "max_current_a": 1.000,       # ±1.0 A
        "min_current_a": 300e-15,
        "max_voltage_v": 12.0,        # ±12 V
        "freq_min_hz": 10e-6,
        "freq_max_hz": 1e6,           # 1 MHz
        "max_scan_rate_v_s": 100.0,
        "min_sample_period_s": 10e-6,
    },
    "INTERFACE 1010": {
        "name": "Gamry Interface 1010",
        "max_current_a": 1.000,
        "min_current_a": 300e-15,
        "max_voltage_v": 12.0,        # ±12 V
        "freq_min_hz": 10e-6,
        "freq_max_hz": 2e6,           # 2 MHz
        "max_scan_rate_v_s": 100.0,
        "min_sample_period_s": 10e-6,
    },
    "INTERFACE 5000": {
        "name": "Gamry Interface 5000",
        "max_current_a": 5.000,       # ±5.0 A
        "min_current_a": 1e-12,
        "max_voltage_v": 6.0,         # ±6 V
        "freq_min_hz": 10e-6,
        "freq_max_hz": 1e6,           # 1 MHz
        "max_scan_rate_v_s": 100.0,
        "min_sample_period_s": 10e-6,
    },
    "REFERENCE 3000": {
        "name": "Gamry Reference 3000",
        "max_current_a": 3.000,       # ±3.0 A
        "min_current_a": 300e-15,
        "max_voltage_v": 32.0,        # ±32 V
        "freq_min_hz": 10e-6,
        "freq_max_hz": 1e6,
        "max_scan_rate_v_s": 100.0,
        "min_sample_period_s": 10e-6,
    },
    "GENERIC": {
        "name": "Generic Potentiostat",
        "max_current_a": 1.000,
        "min_current_a": 1e-12,
        "max_voltage_v": 10.0,
        "freq_min_hz": 10e-6,
        "freq_max_hz": 1e6,
        "max_scan_rate_v_s": 50.0,
        "min_sample_period_s": 1e-4,
    }
}


def get_pstat_info(pstat: Any) -> Dict[str, Any]:
    """
    Extracts label, serial number, model number, and physical limits
    from a live toolkitpy or GamryCOM pstat object.
    """
    label = "Unknown Pstat"
    serial_no = "Unknown S/N"
    model_no = "600"
    
    if pstat is not None:
        for label_attr in ["label", "Label", "Section", "section"]:
            if hasattr(pstat, label_attr):
                try:
                    val = getattr(pstat, label_attr)
                    label = val() if callable(val) else val
                    break
                except Exception:
                    pass
                    
        for sn_attr in ["serial_no", "SerialNo"]:
            if hasattr(pstat, sn_attr):
                try:
                    val = getattr(pstat, sn_attr)
                    serial_no = str(val() if callable(val) else val)
                    break
                except Exception:
                    pass
                    
        for model_attr in ["model_no", "ModelNo"]:
            if hasattr(pstat, model_attr):
                try:
                    val = getattr(pstat, model_attr)
                    model_no = str(val() if callable(val) else val)
                    break
                except Exception:
                    pass

    model_key = label.upper()
    specs = None
    for k, v in MODEL_SPECS.items():
        if k in model_key or model_no in k:
            specs = v.copy()
            break
            
    if specs is None:
        specs = MODEL_SPECS["GENERIC"].copy()
        specs["name"] = f"Gamry Pstat (Model {model_no})"

    if pstat is not None:
        if hasattr(pstat, "freq_limit_lower"):
            try:
                specs["freq_min_hz"] = float(pstat.freq_limit_lower())
            except Exception:
                pass
        if hasattr(pstat, "freq_limit_upper"):
            try:
                specs["freq_max_hz"] = float(pstat.freq_limit_upper())
            except Exception:
                pass

    specs["label"] = label
    specs["serial_no"] = serial_no
    specs["model_no"] = model_no
    return specs


def validate_device_parameters(pstat: Any, config: SequenceConfig, raise_on_error: bool = False) -> List[str]:
    """
    Validates requested configuration parameters against the connected potentiostat model.
    If parameters do not match or exceed capabilities:
      - Issues UserWarning (or raises ValueError if raise_on_error=True).
    Returns a list of warning/error messages.
    """
    specs = get_pstat_info(pstat)
    mismatches: List[str] = []

    model_name = specs["name"]

    # 1. Check OCP parameters
    sample_time = config.ocp.sample_time_s
    min_sp = specs["min_sample_period_s"]
    if sample_time < min_sp:
        mismatches.append(f"[OCP] sample_time_s ({sample_time}s) is smaller than {model_name} minimum sampling period ({min_sp}s).")

    # 2. Check EIS parameters
    eis = config.eis
    init_freq = eis.initial_freq_hz
    final_freq = eis.final_freq_hz
    freq_min = specs["freq_min_hz"]
    freq_max = specs["freq_max_hz"]

    if init_freq > freq_max or init_freq < freq_min:
        mismatches.append(f"[EIS] initial_freq_hz ({init_freq:,.0f} Hz) is outside {model_name} frequency range ({freq_min} - {freq_max:,.0f} Hz).")

    if final_freq > freq_max or final_freq < freq_min:
        mismatches.append(f"[EIS] final_freq_hz ({final_freq:,.0f} Hz) is outside {model_name} frequency range ({freq_min} - {freq_max:,.0f} Hz).")

    ac_v = eis.ac_voltage_v
    dc_v = eis.dc_voltage_v
    max_v = specs["max_voltage_v"]
    if (abs(dc_v) + abs(ac_v)) > max_v:
        mismatches.append(f"[EIS] Combined excitation voltage (DC {dc_v}V + AC {ac_v}V) exceeds {model_name} compliance limit (±{max_v} V).")

    # 3. Check LPR parameters
    scan_rate = config.lpr.scan_rate_v_s
    max_rate = specs["max_scan_rate_v_s"]
    if scan_rate > max_rate:
        mismatches.append(f"[LPR] scan_rate_v_s ({scan_rate} V/s) exceeds {model_name} max scan rate ({max_rate} V/s).")

    # 4. Check CPP parameters
    cpp = config.cpp
    max_rate = specs["max_scan_rate_v_s"]
    max_v = specs["max_voltage_v"]

    for key in ["scan_fwd_v_s", "scan_rev_v_s"]:
        rate = getattr(cpp, key)
        if rate > max_rate:
            mismatches.append(f"[CPP] {key} ({rate} V/s) exceeds {model_name} max scan rate ({max_rate} V/s).")

    for key in ["v_init_v", "v_apex_v", "v_final_v"]:
        v_val = getattr(cpp, key)
        if abs(v_val) > max_v:
            mismatches.append(f"[CPP] {key} ({v_val} V) exceeds {model_name} compliance voltage (±{max_v} V).")

    # Issue warnings or raise error if mismatches found
    if mismatches:
        msg = f"Potentiostat Parameter Mismatch Warning ({model_name}):\n" + "\n".join(f" - {m}" for m in mismatches)
        if raise_on_error:
            raise ValueError(msg)
        else:
            warnings.warn(msg, UserWarning)

    return mismatches


# Backward compatibility helper
def audit_and_clamp_config(pstat: Any, config: SequenceConfig) -> Tuple[SequenceConfig, List[str]]:
    mismatches = validate_device_parameters(pstat, config, raise_on_error=False)
    return config, mismatches

def print_audit_summary(pstat_specs: Dict[str, Any], audit_report: Any) -> None:
    pass
