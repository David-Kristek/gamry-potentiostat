"""Model detection and capability validation, driven by a fake pstat handle.

No hardware: validate_device_parameters reads only duck-typed attributes, so
the whole decision surface is testable on the host interpreter.
"""

from __future__ import annotations

import pytest

from potentiostat.core.hardware.device_validator import (
    audit_and_clamp_config,
    get_pstat_info,
    validate_device_parameters,
)
from potentiostat.parsing.sequence_config import CPPConfig, EISConfig, LPRConfig, OCPConfig, SequenceConfig


# --- get_pstat_info ---------------------------------------------------------


def test_get_pstat_info_matches_label(make_fake_pstat):
    specs = get_pstat_info(make_fake_pstat(label="Reference 600+"))
    assert specs["name"] == "Gamry Reference 600+"
    assert specs["max_voltage_v"] == 11.0
    assert specs["label"] == "Reference 600+"
    assert specs["serial_no"] == "123456"
    assert specs["model_no"] == "REFERENCE 600+"


def test_get_pstat_info_falls_back_to_model_number(make_fake_pstat):
    specs = get_pstat_info(make_fake_pstat(label="Mystery Rig", model_no="INTERFACE 5000"))
    assert specs["name"] == "Gamry Interface 5000"
    assert specs["max_current_a"] == 5.0


def test_get_pstat_info_label_wins_over_model_number(make_fake_pstat):
    specs = get_pstat_info(make_fake_pstat(label="INTERFACE 1000", model_no="REFERENCE 3000"))
    assert specs["name"] == "Gamry Interface 1000"


def test_get_pstat_info_unknown_model_is_generic(make_fake_pstat):
    specs = get_pstat_info(make_fake_pstat(label="Mystery Rig", model_no="ZZZ"))
    assert specs["name"] == "Gamry Pstat (Model ZZZ)"
    assert specs["max_current_a"] == 1.0
    assert specs["max_voltage_v"] == 10.0


def test_get_pstat_info_honours_live_frequency_limits(make_fake_pstat):
    specs = get_pstat_info(make_fake_pstat(label="Mystery Rig", freq_min_hz=1.0, freq_max_hz=1000.0))
    assert specs["freq_min_hz"] == 1.0
    assert specs["freq_max_hz"] == 1000.0


def test_get_pstat_info_without_a_pstat_is_generic():
    specs = get_pstat_info(None)
    assert specs["label"] == "Unknown Pstat"
    assert specs["name"] == "Gamry Pstat (Model unknown)"


# --- validate_device_parameters --------------------------------------------


def test_validate_default_config_reports_no_mismatches(make_fake_pstat):
    pstat = make_fake_pstat(label="Reference 600+")
    assert validate_device_parameters(pstat, SequenceConfig()) == []


def test_validate_flags_ocp_sample_time_below_resolution(make_fake_pstat):
    pstat = make_fake_pstat(label="Reference 600+")
    config = SequenceConfig(ocp=OCPConfig(sample_time_s=1e-9))

    with pytest.warns(UserWarning):
        mismatches = validate_device_parameters(pstat, config)

    assert len(mismatches) == 1
    assert "[OCP]" in mismatches[0]


def test_validate_flags_eis_frequency_out_of_range(make_fake_pstat):
    pstat = make_fake_pstat(label="REFERENCE 600")  # 1 MHz max
    config = SequenceConfig(eis=EISConfig(initial_freq_hz=1e9))

    with pytest.warns(UserWarning):
        mismatches = validate_device_parameters(pstat, config)

    assert any("[EIS]" in m and "initial_freq_hz" in m for m in mismatches)


def test_validate_flags_combined_eis_excitation_voltage(make_fake_pstat):
    pstat = make_fake_pstat(label="Reference 600+")  # 11 V compliance
    config = SequenceConfig(eis=EISConfig(dc_voltage_v=10.5, ac_voltage_v=1.0))

    with pytest.warns(UserWarning):
        mismatches = validate_device_parameters(pstat, config)

    assert any("Combined excitation voltage" in m for m in mismatches)


def test_validate_flags_lpr_scan_rate(make_fake_pstat):
    pstat = make_fake_pstat(label="Reference 600+")
    config = SequenceConfig(lpr=LPRConfig(scan_rate_v_s=1000.0))

    with pytest.warns(UserWarning):
        mismatches = validate_device_parameters(pstat, config)

    assert any("[LPR]" in m for m in mismatches)


def test_validate_flags_cpp_voltage_above_compliance(make_fake_pstat):
    pstat = make_fake_pstat(label="Reference 600+")  # 11 V compliance
    config = SequenceConfig(cpp=CPPConfig(v_apex_v=12.0))

    with pytest.warns(UserWarning):
        mismatches = validate_device_parameters(pstat, config)

    assert any("[CPP]" in m and "v_apex_v" in m for m in mismatches)


def test_validate_raises_when_requested(make_fake_pstat):
    pstat = make_fake_pstat(label="Reference 600+")
    config = SequenceConfig(cpp=CPPConfig(v_apex_v=12.0))

    with pytest.raises(ValueError, match="Mismatch"):
        validate_device_parameters(pstat, config, raise_on_error=True)


def test_audit_and_clamp_config_returns_config_and_messages(make_fake_pstat):
    pstat = make_fake_pstat(label="Reference 600+")
    config = SequenceConfig(lpr=LPRConfig(scan_rate_v_s=1000.0))

    with pytest.warns(UserWarning):
        returned, mismatches = audit_and_clamp_config(pstat, config)

    assert returned is config
    assert mismatches
