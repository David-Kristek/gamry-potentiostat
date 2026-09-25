"""Live status bookkeeping: the JSON plot payloads (and their thinning), the
fraction-complete math, the tracker's reaction to workflow events, and the
parse-back used by hosts."""

from __future__ import annotations

import math

import numpy as np

from potentiostat.core.workflow.emitter import (
    TechniqueErrorEvent,
    TechniqueFinishEvent,
    TechniqueProgressEvent,
    WorkflowEmitter,
)
from potentiostat.utils.sequence_status import (
    CurrentTechniqueStatus,
    SequencePhase,
    SequenceRunStatus,
    SequenceStatusTracker,
    _build_plot_payload,
    _log_abs,
    _plot_payload,
    _thin_pair,
    _thin_payload,
    parse_sequence_status,
)


def _curve(**columns):
    dtype = [(name, "f8") for name in columns]
    return np.array(list(zip(*columns.values())), dtype=dtype)


# --- payload building -------------------------------------------------------


def test_log_abs_treats_zero_as_a_gap():
    assert _log_abs(0) is None
    assert _log_abs(-100) == 2.0
    assert _log_abs(1000) == 3.0


def test_build_plot_payload_for_ocp_and_lpr():
    ocp = _build_plot_payload("ocp", _curve(time=[0.0, 1.0], vf=[0.1, 0.2]))
    assert ocp == {"x": [0.0, 1.0], "y": [0.1, 0.2], "xlabel": "Time (s)", "ylabel": "OCP (V)"}

    lpr = _build_plot_payload("lpr", _curve(vf=[-0.1, 0.0], im=[1e-6, 2e-6]))
    assert lpr["xlabel"] == "Potential (V)"
    assert lpr["ylabel"] == "Current (A)"
    assert lpr["y"] == [1e-6, 2e-6]


def test_build_plot_payload_for_cpp_negates_nothing_but_logs_current():
    payload = _build_plot_payload("cpp", _curve(im=[1e-6, 1e-5], vf=[-0.1, 0.0]))
    assert payload["x"] == [math.log10(1e-6), math.log10(1e-5)]
    assert payload["y"] == [-0.1, 0.0]
    assert payload["xlabel"] == "log|I| (A)"


def test_build_plot_payload_for_eis_nyquist_flips_sign_of_zimag():
    data = _curve(
        zreal=[1.0, 2.0],
        zimag=[0.5, 1.5],
        zfreq=[100.0, 10.0],
        zmod=[1.12, 2.5],
        zphz=[-26.5, -36.8],
    )
    payload = _build_plot_payload("eis", data)
    assert set(payload) == {"nyquist", "bode_mag", "bode_phase"}
    assert payload["nyquist"] == {"x": [1.0, 2.0], "y": [-0.5, -1.5]}
    assert payload["bode_mag"] == {"x": [100.0, 10.0], "y": [1.12, 2.5]}


def test_build_plot_payload_returns_none_for_empty_or_unknown():
    assert _build_plot_payload("ocp", None) is None
    assert _build_plot_payload("ocp", _curve(time=[], vf=[])) is None
    assert _build_plot_payload("not-a-technique", _curve(a=[1.0])) is None


# --- thinning ---------------------------------------------------------------


def test_thin_pair_downsamples_long_series():
    x = list(range(2500))
    y = list(range(2500))
    out_x, out_y = _thin_pair(x, y, max_points=1000)
    step = math.ceil(2500 / 1000)  # 3
    assert len(out_x) == math.ceil(2500 / step)
    assert out_x[:3] == [0, 3, 6]
    assert out_y[:3] == [0, 3, 6]


def test_thin_pair_leaves_short_series_untouched():
    x, y = [1, 2, 3], [4, 5, 6]
    out_x, out_y = _thin_pair(x, y, max_points=1000)
    assert out_x is x and out_y is y


def test_thin_payload_thins_each_eis_subpanel():
    payload = {
        "nyquist": {"x": list(range(10)), "y": list(range(10))},
        "bode_mag": {"x": list(range(10)), "y": list(range(10))},
    }
    thinned = _thin_payload(payload, max_points=5)
    assert len(thinned["nyquist"]["x"]) == 5
    assert len(thinned["bode_mag"]["x"]) == 5


def test_plot_payload_is_thinned():
    data = _curve(time=list(range(5000)), vf=list(range(5000)))
    payload = _plot_payload("ocp", data)
    assert len(payload["x"]) < 5000


# --- status models ----------------------------------------------------------


def test_current_technique_fraction_complete():
    assert CurrentTechniqueStatus(technique="OCP", elapsed_s=30.0, estimated_time_left=70.0).fraction_complete == 0.3
    assert CurrentTechniqueStatus(technique="OCP", elapsed_s=30.0).fraction_complete is None
    assert CurrentTechniqueStatus(technique="OCP", elapsed_s=0.0, estimated_time_left=0.0).fraction_complete is None


def test_sequence_run_status_elapsed_uses_end_when_set():
    status = SequenceRunStatus(technique_keys=["ocp"], sequenec_start_s=100.0, outdir="out", sequence_end_s=160.0)
    assert status.time_elapsed_s == 60.0


def test_parse_sequence_status_round_trips():
    status = SequenceRunStatus(technique_keys=["ocp", "eis"], sequenec_start_s=1.0, outdir="out")
    assert parse_sequence_status(status.model_dump(mode="json")) == status


# --- tracker ----------------------------------------------------------------


def _tracker():
    emitter = WorkflowEmitter()
    tracker = SequenceStatusTracker(
        ["ocp", "eis"],
        outdir="out",
        emitter=emitter,
        emit_interval_s=0.0,  # never throttle, so tests are deterministic
    )
    return emitter, tracker


def test_tracker_records_progress_and_plot():
    emitter, tracker = _tracker()

    emitter.emit(
        TechniqueProgressEvent(
            key="ocp",
            technique_name="OCP",
            data=_curve(time=[0.0, 1.0, 2.0], vf=[0.1, 0.2, 0.3]),
            elapsed_s=1.0,
            estimated_time_left=9.0,
        )
    )

    assert tracker.status.phase is SequencePhase.RUNNING
    assert tracker.status.technique_index == 0
    assert tracker.status.plots["ocp"]["x"] == [0.0, 1.0, 2.0]
    assert tracker.status.current_technique.technique == "OCP"
    assert tracker.status.extra == "3 point(s) collected"


def test_tracker_handles_finish_and_error():
    emitter, tracker = _tracker()

    emitter.emit(TechniqueFinishEvent(key="ocp", technique_name="OCP", e_ocp=0.2, csv_path="a.csv", dta_path="a.dta"))
    assert tracker.status.phase is SequencePhase.RUNNING
    assert tracker.status.extra == "done"
    assert tracker.status.current_technique.estimated_time_left == 0.0

    emitter.emit(TechniqueErrorEvent(key="eis", technique_name="EIS", error="boom"))
    assert tracker.status.phase is SequencePhase.ERROR
    assert tracker.status.technique_index == 1
    assert tracker.status.extra == "error: boom"


def test_tracker_terminal_phases_and_snapshot_is_a_copy():
    _, tracker = _tracker()

    tracker.sequence_error("nope")
    assert tracker.status.phase is SequencePhase.ERROR
    assert tracker.status.sequence_end_s is not None

    tracker.sequence_done()
    assert tracker.status.phase is SequencePhase.DONE

    tracker.sequence_abort()
    assert tracker.status.phase is SequencePhase.STOPPED

    snapshot = tracker.get_snapshot()
    snapshot.extra = "mutated"
    assert tracker.status.extra != "mutated"
