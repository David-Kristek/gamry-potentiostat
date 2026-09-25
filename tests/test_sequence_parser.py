"""Parsing a Gamry .GSequence XML into a validated SequenceConfig, including
the mV->V unit conversions and the missing-file fallback."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from potentiostat.parsing.sequence_config import SequenceConfig
from potentiostat.parsing.sequence_parser import (
    compile_gsequence,
    parse_element_params,
    parse_gsequence,
)

GSEQUENCE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<sequence>
  <element>
    <classname>OCP</classname>
    <name>Open Circuit Potential</name>
    <parameters>
      <quantity tag="TIMEOUT" value="120"/>
      <quantity tag="SAMPLETIME" value="0.25"/>
      <quantity tag="AREA" value="0.57"/>
    </parameters>
  </element>
  <element>
    <classname>EISPOT</classname>
    <name>Potentiostatic EIS</name>
    <parameters>
      <explain_poten tag="VDC" value="0.25" versus="1"/>
      <quantity tag="VAC" value="20"/>
      <quantity tag="FREQINIT" value="100000"/>
      <quantity tag="FREQFINAL" value="0.1"/>
      <quantity tag="PTSPERDEC" value="10"/>
      <quantity tag="ZGUESS" value="100"/>
      <quantity tag="SPEED" value="1"/>
      <option tag="DRIFTCOR" checked="1"/>
    </parameters>
  </element>
  <element>
    <classname>POLRES</classname>
    <name>Polarization Resistance</name>
    <parameters>
      <explain_poten tag="VINIT" value="-0.02" versus="1"/>
      <explain_poten tag="VFINAL" value="0.02" versus="1"/>
      <quantity tag="SCANRATE" value="0.25"/>
      <quantity tag="SAMPLETIME" value="1.0"/>
      <quantity tag="AREA" value="0.57"/>
      <quantity tag="DENSITY" value="7.87"/>
      <quantity tag="EQUIV" value="27.92"/>
      <quantity tag="BETAA" value="0.12"/>
      <quantity tag="BETAC" value="0.12"/>
    </parameters>
  </element>
  <element>
    <classname>CYCPOL</classname>
    <name>Cyclic Polarization Scan</name>
    <parameters>
      <explain_poten tag="VINIT" value="-0.1" versus="0"/>
      <explain_poten tag="VAPEX" value="1.2" versus="1"/>
      <explain_poten tag="VFINAL" value="0.0" versus="1"/>
      <quantity tag="SCANFWD" value="2"/>
      <quantity tag="SCANREV" value="5"/>
      <quantity tag="ILIMIT" value="5.0"/>
      <quantity tag="SAMPLETIME" value="1.0"/>
      <quantity tag="AREA" value="0.57"/>
    </parameters>
  </element>
  <element>
    <classname>NOT_A_TECHNIQUE</classname>
    <parameters>
      <quantity tag="X" value="1"/>
    </parameters>
  </element>
</sequence>
"""


def _write_gsequence(tmp_path):
    path = tmp_path / "sample.GSequence"
    path.write_text(GSEQUENCE_XML, encoding="utf-8")
    return path


def test_parse_gsequence_populates_every_technique(tmp_path):
    config = parse_gsequence(str(_write_gsequence(tmp_path)))

    assert config.ocp.total_time_s == 120.0
    assert config.ocp.sample_time_s == 0.25
    assert config.ocp.title == "Open Circuit Potential"

    # VAC is stored in mV in the XML and converted to V.
    assert config.eis.ac_voltage_v == 0.02
    assert config.eis.dc_voltage_v == 0.25
    assert config.eis.dc_versus_eoc is True
    assert config.eis.initial_freq_hz == 100000.0
    assert config.eis.final_freq_hz == 0.1
    assert config.eis.points_per_decade == 10
    assert config.eis.drift_correction is True

    assert config.lpr.v_init_v == -0.02
    assert config.lpr.v_init_versus_eoc is True
    assert config.lpr.v_final_v == 0.02
    # SCANRATE is stored in mV/s and converted to V/s.
    assert config.lpr.scan_rate_v_s == 0.00025
    assert config.lpr.beta_a_v_dec == 0.12

    assert config.cpp.v_init_v == -0.1
    assert config.cpp.v_init_versus_eoc is False
    assert config.cpp.v_apex_v == 1.2
    assert config.cpp.v_final_v == 0.0
    assert config.cpp.scan_fwd_v_s == 0.002
    assert config.cpp.scan_rev_v_s == 0.005
    assert config.cpp.i_limit_ma_cm2 == 5.0


def test_unknown_classnames_are_ignored(tmp_path):
    # Parsing must not raise on a non-technique element; defaults stand.
    config = parse_gsequence(str(_write_gsequence(tmp_path)))
    assert config.cpp.title == "Cyclic Polarization Scan"


def test_missing_file_falls_back_to_defaults(tmp_path):
    config = parse_gsequence(str(tmp_path / "does-not-exist.GSequence"))
    assert config == SequenceConfig()


def test_parse_element_params_unit_conversions():
    element = ET.fromstring(
        """
        <element>
          <name>Test</name>
          <parameters>
            <quantity tag="VAC" value="10"/>
            <quantity tag="SCANRATE" value="250"/>
            <explain_poten tag="VDC" value="0.25" versus="1"/>
            <option tag="DRIFTCOR" checked="1"/>
            <quantity tag="NOVALUE"/>
          </parameters>
        </element>
        """
    )

    params = parse_element_params(element)

    assert params["title"] == "Test"
    assert params["ac_voltage_v"] == 0.01  # 10 mV -> 0.01 V
    assert params["scan_rate_v_s"] == 0.25  # 250 mV/s -> 0.25 V/s
    assert params["VDC"] == {"value": "0.25", "versus": "1"}
    assert params["DRIFTCOR"] == "1"
    assert "NOVALUE" not in params  # tag present but no value/checked/index


def test_parse_element_params_without_parameters_block():
    element = ET.fromstring("<element><name>Only a title</name></element>")
    assert parse_element_params(element) == {"title": "Only a title"}


def test_compile_gsequence_writes_json(tmp_path):
    xml_path = _write_gsequence(tmp_path)
    json_path = tmp_path / "sequence.json"

    config = compile_gsequence(str(xml_path), str(json_path))

    assert json_path.is_file()
    assert SequenceConfig.load(str(json_path)) == config
