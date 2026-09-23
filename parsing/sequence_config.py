import json
import os
from typing import Dict, Any
from pydantic import BaseModel, Field, field_validator, model_validator

class GamryBaseConfig(BaseModel):
    model_config = {
        "populate_by_name": True
    }

class OCPConfig(GamryBaseConfig):
    title: str = "Open Circuit Potential"
    output: str = "OCP.DTA"
    total_time_s: float = Field(300.0, alias="TIMEOUT")
    sample_time_s: float = Field(0.5, alias="SAMPLETIME")
    area_cm2: float = Field(0.57, alias="AREA")

    @field_validator("total_time_s", "sample_time_s", "area_cm2", mode="before")
    @classmethod
    def to_float(cls, v):
        return float(v)

class EISConfig(GamryBaseConfig):
    title: str = "Potentiostatic EIS"
    output: str = "EISPOT.DTA"
    dc_voltage_v: float = 0.0
    dc_versus_eoc: bool = True
    initial_freq_hz: float = Field(100000.0, alias="FREQINIT")
    final_freq_hz: float = Field(0.1, alias="FREQFINAL")
    points_per_decade: int = Field(10, alias="PTSPERDEC")
    ac_voltage_v: float = Field(0.010, alias="ac_voltage_v") # in Volts
    area_cm2: float = Field(0.57, alias="AREA")
    estimated_z_ohm: float = Field(100.0, alias="ZGUESS")
    speed: int = Field(1, alias="SPEED")
    drift_correction: bool = Field(False, alias="DRIFTCOR")

    @field_validator("initial_freq_hz", "final_freq_hz", "area_cm2", "estimated_z_ohm", "ac_voltage_v", mode="before")
    @classmethod
    def to_float(cls, v):
        return float(v)

    @field_validator("points_per_decade", mode="before")
    @classmethod
    def to_int(cls, v):
        return int(v)

    @field_validator("speed", mode="before")
    @classmethod
    def parse_speed(cls, v):
        return int(v)

    @field_validator("drift_correction", mode="before")
    @classmethod
    def parse_drift(cls, v):
        return v == "1" if isinstance(v, str) else bool(v)

    @model_validator(mode="before")
    @classmethod
    def parse_vdc(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        vdc_data = data.get("VDC")
        if isinstance(vdc_data, dict):
            data["dc_voltage_v"] = float(vdc_data.get("value", 0.0))
            data["dc_versus_eoc"] = vdc_data.get("versus") == "1"
        elif "dc_voltage_v" not in data:
            data["dc_voltage_v"] = float(data.get("dc_voltage_v", 0.0))
            data["dc_versus_eoc"] = bool(data.get("dc_versus_eoc", True))
        return data

class LPRConfig(GamryBaseConfig):
    title: str = "Polarization Resistance"
    output: str = "POLRES.DTA"
    v_init_v: float = -0.015
    v_init_versus_eoc: bool = True
    v_final_v: float = 0.015
    v_final_versus_eoc: bool = True
    scan_rate_v_s: float = Field(0.000125, alias="scan_rate_v_s") # in V/s
    sample_time_s: float = Field(1.0, alias="SAMPLETIME")
    area_cm2: float = Field(0.57, alias="AREA")
    density_g_cm3: float = Field(7.87, alias="DENSITY")
    equiv_weight: float = Field(27.92, alias="EQUIV")
    beta_a_v_dec: float = Field(0.12, alias="BETAA")
    beta_c_v_dec: float = Field(0.12, alias="BETAC")

    @field_validator(
        "sample_time_s", "area_cm2", "scan_rate_v_s",
        "density_g_cm3", "equiv_weight", "beta_a_v_dec", "beta_c_v_dec",
        mode="before",
    )
    @classmethod
    def to_float(cls, v):
        return float(v)

    @model_validator(mode="before")
    @classmethod
    def parse_poten(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        vinit_data = data.get("VINIT")
        if isinstance(vinit_data, dict):
            data["v_init_v"] = float(vinit_data.get("value", -0.015))
            data["v_init_versus_eoc"] = vinit_data.get("versus") == "1"
        elif "v_init_v" not in data:
            data["v_init_v"] = float(data.get("v_init_v", -0.015))
            data["v_init_versus_eoc"] = bool(data.get("v_init_versus_eoc", True))

        vfinal_data = data.get("VFINAL")
        if isinstance(vfinal_data, dict):
            data["v_final_v"] = float(vfinal_data.get("value", 0.015))
            data["v_final_versus_eoc"] = vfinal_data.get("versus") == "1"
        elif "v_final_v" not in data:
            data["v_final_v"] = float(data.get("v_final_v", 0.015))
            data["v_final_versus_eoc"] = bool(data.get("v_final_versus_eoc", True))
        return data

class CPPConfig(GamryBaseConfig):
    title: str = "Cyclic Polarization Scan"
    output: str = "CYCPOL.DTA"
    v_init_v: float = -0.25
    v_init_versus_eoc: bool = True
    scan_fwd_v_s: float = Field(0.001, alias="scan_fwd_v_s") # in V/s
    v_apex_v: float = 1.5
    v_apex_versus_eoc: bool = True
    scan_rev_v_s: float = Field(0.0025, alias="scan_rev_v_s") # in V/s
    v_final_v: float = 0.0
    v_final_versus_eoc: bool = True
    sample_time_s: float = Field(1.0, alias="SAMPLETIME")
    area_cm2: float = Field(0.57, alias="AREA")
    density_g_cm3: float = Field(7.87, alias="DENSITY")
    equiv_weight: float = Field(27.92, alias="EQUIV")
    i_limit_ma_cm2: float = Field(5.0, alias="ILIMIT")
    # Not a Gamry Sequence Wizard field -- "two_leg" (default, run_cpp) stitches two
    # signal_ramp_new legs and supports ASTM G61 current-triggered reversal;
    # "single_signal" (run_cpp_single_signal) uses one signal_r_up_dn_new sweep like
    # Gamry_ToolkitPy_Docs/scripts_examples/CV.py, fixed-apex only. Change this default
    # (or set it in a .json), since a parsed .GSequence never carries it.
    signal_mode: str = "two_leg"

    @field_validator(
        "sample_time_s", "area_cm2", "scan_fwd_v_s", "scan_rev_v_s",
        "density_g_cm3", "equiv_weight", "i_limit_ma_cm2",
        mode="before",
    )
    @classmethod
    def to_float(cls, v):
        return float(v)

    @model_validator(mode="before")
    @classmethod
    def parse_poten(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        for tag, field, default in [("VINIT", "v_init_v", -0.25), ("VAPEX", "v_apex_v", 1.5), ("VFINAL", "v_final_v", 0.0)]:
            val_data = data.get(tag)
            if isinstance(val_data, dict):
                data[field] = float(val_data.get("value", default))
                data[f"{field}_versus_eoc"] = val_data.get("versus") == "1"
            elif field not in data:
                data[field] = float(data.get(field, default))
                data[f"{field}_versus_eoc"] = bool(data.get(f"{field}_versus_eoc", True))
        return data

class SequenceConfig(BaseModel):
    """The full ocp/eis/lpr/cpp technique parameter set for one measurement
    sequence -- what a .GSequence/sequence.json compiles down to."""

    ocp: OCPConfig = Field(default_factory=OCPConfig)
    eis: EISConfig = Field(default_factory=EISConfig)
    lpr: LPRConfig = Field(default_factory=LPRConfig)
    cpp: CPPConfig = Field(default_factory=CPPConfig)


    def save(self, file_path: str) -> None:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(self.model_dump(), f, indent=2)
            f.write("\n")
    @classmethod
    def load(cls, file_path: str = "") -> "SequenceConfig":
        """Loads a SequenceConfig from a .json or .GSequence file. If the file does not exist, returns a default config."""
        if file_path == "" or not os.path.exists(file_path):
                    return cls()
        if file_path.lower().endswith(".gsequence"):
            # Imported lazily: sequence_parser imports the config classes from
            # this module at import time, so a top-level import here is circular.
            from potentiostat.parsing import sequence_parser

            return sequence_parser.parse_gsequence(file_path)
        else: 
            with open(file_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            return cls.model_validate(raw)
        
