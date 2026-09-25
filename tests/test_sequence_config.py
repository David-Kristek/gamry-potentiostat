"""The SequenceConfig contract: Gamry aliases, the string->float coercion the
.GSequence reader relies on, and the VDC/VINIT/VFINAL/VAPEX dict decoding."""

from __future__ import annotations

import json

import pytest

from potentiostat.parsing.sequence_config import (
    CPPConfig,
    EISConfig,
    LPRConfig,
    OCPConfig,
    SequenceConfig,
)


def test_ocp_reads_gamry_aliases_and_coerces_strings():
    cfg = OCPConfig(**{"TIMEOUT": "120", "SAMPLETIME": "0.25", "AREA": "1.0"})
    assert cfg.total_time_s == 120.0
    assert cfg.sample_time_s == 0.25
    assert cfg.area_cm2 == 1.0


def test_eis_decodes_vdc_explain_potential():
    cfg = EISConfig(**{"VDC": {"value": "0.25", "versus": "1"}})
    assert cfg.dc_voltage_v == 0.25
    assert cfg.dc_versus_eoc is True

    cfg = EISConfig(**{"VDC": {"value": "-0.1", "versus": "0"}})
    assert cfg.dc_voltage_v == -0.1
    assert cfg.dc_versus_eoc is False


def test_eis_accepts_plain_dc_fields_when_versus_is_given_directly():
    cfg = EISConfig(dc_voltage_v="-0.3", dc_versus_eoc=False)
    assert cfg.dc_voltage_v == -0.3
    assert cfg.dc_versus_eoc is False


def test_eis_drift_correction_parses_gamry_checkbox():
    assert EISConfig(**{"DRIFTCOR": "1"}).drift_correction is True
    assert EISConfig(**{"DRIFTCOR": "0"}).drift_correction is False
    assert EISConfig(drift_correction=True).drift_correction is True


def test_lpr_decodes_vinit_and_vfinal():
    cfg = LPRConfig(**{"VINIT": {"value": "-0.02", "versus": "1"}, "VFINAL": {"value": "0.02", "versus": "0"}})
    assert cfg.v_init_v == -0.02
    assert cfg.v_init_versus_eoc is True
    assert cfg.v_final_v == 0.02
    assert cfg.v_final_versus_eoc is False


def test_cpp_decodes_vinit_apex_and_final_and_keeps_other_defaults():
    cfg = CPPConfig(**{"VINIT": {"value": "-0.1", "versus": "0"}})
    assert cfg.v_init_v == -0.1
    assert cfg.v_init_versus_eoc is False
    # Tags absent from the XML must fall back to the field defaults.
    assert cfg.v_apex_v == 1.5
    assert cfg.v_apex_versus_eoc is True
    assert cfg.v_final_v == 0.0
    assert cfg.signal_mode == "two_leg"


def test_save_load_round_trip(tmp_path):
    cfg = SequenceConfig(
        ocp=OCPConfig(total_time_s=42.0),
        eis=EISConfig(initial_freq_hz=5000.0, ac_voltage_v=0.02),
        cpp=CPPConfig(signal_mode="single_signal"),
    )
    path = tmp_path / "sequence.json"

    cfg.save(str(path))

    # Valid JSON, pretty-printed, trailing newline.
    text = path.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert json.loads(text)["ocp"]["total_time_s"] == 42.0

    assert SequenceConfig.load(str(path)) == cfg


def test_load_returns_default_when_path_missing(tmp_path):
    assert SequenceConfig.load("") == SequenceConfig()
    assert SequenceConfig.load(str(tmp_path / "nope.json")) == SequenceConfig()


@pytest.mark.parametrize("cls", [OCPConfig, EISConfig, LPRConfig, CPPConfig])
def test_configs_round_trip_through_model_dump(cls):
    cfg = cls()
    assert cls.model_validate(cfg.model_dump()) == cfg
