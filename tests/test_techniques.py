"""The Technique base class: registry, progress estimation, dataframe/CSV
conversion, and the sequencing validation that runs before hardware is touched."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pyproc_bridge import AbortError, AbortSignal

from potentiostat.core.sequence.sequence import ExecuteSequenceConfig, execute_sequence_sync
from potentiostat.core.techniques import Technique
from potentiostat.core.techniques.run_cpp import CPP, _concat_leg_data
from potentiostat.core.techniques.run_eis import EIS, _estimated_eis_points
from potentiostat.core.techniques.run_lpr import LPR
from potentiostat.core.techniques.run_ocp import OCP
from potentiostat.core.techniques.technique import (
    SequenceResults,
    TechniqueContext,
    TechniqueOutcome,
)
from potentiostat.parsing.sequence_config import (
    CPPConfig,
    EISConfig,
    GamryBaseConfig,
    LPRConfig,
    OCPConfig,
    SequenceConfig,
)


class _FakeTechnique(Technique[GamryBaseConfig]):
    """No analytic duration and no ETA override, to reach the base fallback."""

    name = "test_fake"
    col_mapping = {}

    def _initialize(self, ctx):  # pragma: no cover - never run here
        pass

    def _measure(self, ctx):  # pragma: no cover - never run here
        return {}, 0.0


# --- registry ---------------------------------------------------------------


def test_registry_contains_the_four_techniques():
    techniques = Technique.all_techniques()
    assert techniques["ocp"] is OCP
    assert techniques["eis"] is EIS
    assert techniques["lpr"] is LPR
    assert techniques["cpp"] is CPP


def test_get_resolves_registered_techniques_and_rejects_unknown():
    assert Technique.get("eis") is EIS
    with pytest.raises(ValueError, match="not registered"):
        Technique.get("nope")


def test_from_key_strips_occurrence_suffix():
    assert Technique.from_key("eis_2") is EIS
    assert Technique.from_key("ocp") is OCP


# --- progress estimation ----------------------------------------------------


def test_estimated_total_points_from_duration_and_sample_time():
    assert OCP.estimated_total_points(OCPConfig(total_time_s=300.0, sample_time_s=0.5)) == 600
    assert LPR.estimated_total_points(LPRConfig()) == 240
    assert CPP.estimated_total_points(CPPConfig()) == 2350


def test_estimated_total_points_is_none_without_a_duration():
    assert _FakeTechnique.estimated_total_points(None) is None


def test_estimated_eis_points_matches_toolkitpy_formula():
    # 5 decades at 10 points/decade, both ends on exact decades -> 61 points.
    assert _estimated_eis_points(1e5, 0.1, 10) == 61
    assert EIS.estimated_total_points(EISConfig()) == 61


def test_estimate_remaining_time_uses_analytic_duration():
    eta = OCP.estimate_remaining_time(
        OCPConfig(total_time_s=100.0), elapsed_s=40.0, points_collected=10, total_points=100
    )
    assert eta == 60.0


def test_eis_estimate_remaining_time_is_intentionally_disabled():
    assert EIS.estimate_remaining_time(EISConfig(), elapsed_s=1.0, points_collected=1, total_points=10) is None


def test_base_estimate_remaining_time_extrapolates_from_points():
    # 5 points in 10 s -> 2 s/point; 15 points remain -> 30 s.
    assert _FakeTechnique.estimate_remaining_time(None, elapsed_s=10.0, points_collected=5, total_points=20) == 30.0
    assert _FakeTechnique.estimate_remaining_time(None, elapsed_s=10.0, points_collected=0, total_points=20) is None
    assert _FakeTechnique.estimate_remaining_time(None, elapsed_s=10.0, points_collected=5, total_points=0) is None
    # Already at/over the point budget -> zero left.
    assert _FakeTechnique.estimate_remaining_time(None, elapsed_s=10.0, points_collected=25, total_points=20) == 0.0


# --- dataframe / CSV conversion ---------------------------------------------


def test_to_dataframe_maps_columns_via_col_mapping():
    arr = np.array([(0.0, 0.1), (1.0, 0.2)], dtype=[("time", "f8"), ("vf", "f8")])
    df = OCP().to_dataframe(arr)
    assert list(df.columns) == ["Time (s)", "OCP (V)"]
    assert list(df["OCP (V)"]) == [0.1, 0.2]


def test_to_dataframe_rejects_missing_fields():
    arr = np.array([(0.0,)], dtype=[("time", "f8")])
    with pytest.raises(ValueError, match="not found in data dtype names"):
        OCP().to_dataframe(arr)


def test_eis_to_dataframe_negates_zimag():
    arr = np.array(
        [(1.0, 0.5, 100.0, 1.12, -26.5)],
        dtype=[("zreal", "f8"), ("zimag", "f8"), ("zfreq", "f8"), ("zmod", "f8"), ("zphz", "f8")],
    )
    df = EIS().to_dataframe(arr)
    assert df["-ZIm (Ohm)"].iloc[0] == -0.5


def test_cpp_to_dataframe_tags_legs():
    arr = np.array([(0.0, 1e-6), (0.1, 2e-6)], dtype=[("vf", "f8"), ("im", "f8")])
    tagged = CPP().to_dataframe(arr, legs=["CURVE1", "CURVE2"])
    assert list(tagged["Leg"]) == ["CURVE1", "CURVE2"]

    untagged = CPP().to_dataframe(arr)
    assert list(untagged["Leg"]) == ["CURVE", "CURVE"]


def test_get_empty_df_is_shaped_like_output():
    df = OCP.get_empty_df()
    assert list(df.columns) == ["Time (s)", "OCP (V)"]
    assert df.empty


def test_write_csv_round_trips(tmp_path):
    arr = np.array([(0.0, 0.1), (1.0, 0.2)], dtype=[("vf", "f8"), ("im", "f8")])
    path = tmp_path / "cpp.csv"

    CPP().write_csv(str(path), {"data": arr, "dta_path": "", "csv_path": str(path), "legs": ["CURVE1", "CURVE2"]})

    df = pd.read_csv(path)
    assert list(df.columns) == ["Potential_V", "Current_A", "Leg"]
    assert list(df["Leg"]) == ["CURVE1", "CURVE2"]


def test_concat_leg_data_continues_point_and_time_columns():
    dtype = [("point", "i8"), ("time", "f8"), ("vf", "f8")]
    fwd = np.array([(0, 0.0, 0.1), (1, 1.0, 0.2)], dtype=dtype)
    rev = np.array([(0, 0.0, 0.15), (1, 1.0, 0.05)], dtype=dtype)

    out = _concat_leg_data(fwd, rev, sample_time=1.0)

    assert list(out["point"]) == [0, 1, 2, 3]
    assert list(out["time"]) == [0.0, 1.0, 2.0, 3.0]
    assert list(out["vf"]) == [0.1, 0.2, 0.15, 0.05]


def test_concat_leg_data_passes_through_single_legs():
    dtype = [("point", "i8"), ("time", "f8"), ("vf", "f8")]
    fwd = np.array([(0, 0.0, 0.1)], dtype=dtype)
    empty = np.array([], dtype=dtype)
    assert _concat_leg_data(fwd, empty, 1.0) is fwd


# --- context / results ------------------------------------------------------


def test_context_from_sequence_builds_paths_and_config():
    ctx = TechniqueContext.from_sequence(
        key="ocp",
        tkp=None,
        pstat=None,
        config=SequenceConfig(),
        technique_name="ocp",
        e_ocp=0.123,
        outdir="out",
    )
    assert isinstance(ctx.cfg, OCPConfig)
    assert ctx.csv_path.endswith("ocp.csv")
    assert ctx.dta_path.endswith("ocp.dta")
    assert ctx.e_ocp == 0.123
    assert ctx.emitter.technique_name == "ocp"


def test_sequence_results_is_keyed_by_technique():
    outcome = TechniqueOutcome(dta_path="a.dta", csv_path="a.csv")
    results = SequenceResults({"ocp": outcome})
    assert results["ocp"] is outcome
    assert dict(results.items()) == {"ocp": outcome}
    assert list(iter(results)) == ["ocp"]


def test_technique_outcome_defaults_legs_to_none():
    assert TechniqueOutcome(dta_path="a.dta", csv_path="a.csv").legs is None


# --- sequence validation (before any hardware is touched) -------------------


def test_sequence_must_start_with_ocp():
    cfg = ExecuteSequenceConfig(technique_keys=["eis", "lpr"], outdir="out")
    with pytest.raises(ValueError, match="start with 'ocp'"):
        execute_sequence_sync(cfg, abort=AbortSignal())


def test_sequence_keys_must_be_unique():
    cfg = ExecuteSequenceConfig(technique_keys=["ocp", "ocp"], outdir="out")
    with pytest.raises(ValueError, match="must be unique"):
        execute_sequence_sync(cfg, abort=AbortSignal())


def test_already_aborted_sequence_does_not_touch_hardware():
    abort = AbortSignal()
    abort.abort()
    cfg = ExecuteSequenceConfig(technique_keys=["ocp"], outdir="out")
    with pytest.raises(AbortError):
        execute_sequence_sync(cfg, abort=abort)
