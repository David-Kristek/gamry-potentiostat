"""Workflow telemetry: the ndarray wire round-trip (field names must survive
the IPC hop) and the type-keyed host-side fan-out."""

from __future__ import annotations

import numpy as np
import pytest

from potentiostat.core.workflow.emitter import (
    TechniqueErrorEvent,
    TechniqueFinishEvent,
    TechniqueProgressEvent,
    TechniqueStartEvent,
    WorkflowEmitter,
    _dump_ndarray,
    _load_ndarray,
    dump_workflow_event,
    parse_workflow_event,
)


def _structured_curve():
    return np.array(
        [(0.0, 0.10), (1.0, 0.20), (2.0, 0.30)],
        dtype=[("time", "f8"), ("vf", "f8")],
    )


def test_dump_ndarray_keeps_field_names():
    dumped = _dump_ndarray(_structured_curve())
    assert dumped["fields"] == ["time", "vf"]
    # Structured .tolist() yields row tuples; JSON turns them into lists, and
    # _load_ndarray accepts either.
    assert dumped["rows"] == [(0.0, 0.1), (1.0, 0.2), (2.0, 0.3)]


def test_ndarray_round_trip_preserves_structured_dtype():
    loaded = _load_ndarray(_dump_ndarray(_structured_curve()))
    assert loaded.dtype.names == ("time", "vf")
    np.testing.assert_allclose(loaded["time"], [0.0, 1.0, 2.0])
    np.testing.assert_allclose(loaded["vf"], [0.1, 0.2, 0.3])


def test_plain_1d_ndarray_round_trip():
    arr = np.array([1.0, 2.0, 3.0])
    dumped = _dump_ndarray(arr)
    assert dumped == [1.0, 2.0, 3.0]
    np.testing.assert_allclose(_load_ndarray(dumped), arr)


def test_progress_event_round_trip_through_wire_form():
    event = TechniqueProgressEvent(
        key="ocp",
        technique_name="OCP",
        data=_structured_curve(),
        elapsed_s=1.5,
        estimated_time_left=8.5,
    )

    restored = parse_workflow_event(dump_workflow_event(event))

    assert isinstance(restored, TechniqueProgressEvent)
    assert restored.key == "ocp"
    assert restored.elapsed_s == 1.5
    assert restored.estimated_time_left == 8.5
    # The whole point of the custom (de)serializer: named fields still work.
    assert restored.data.dtype.names == ("time", "vf")
    np.testing.assert_allclose(restored.data["vf"], [0.1, 0.2, 0.3])


@pytest.mark.parametrize(
    "event",
    [
        TechniqueStartEvent(key="ocp", technique_name="OCP"),
        TechniqueProgressEvent(
            key="ocp", technique_name="OCP", data=_structured_curve(), elapsed_s=0.0, estimated_time_left=None
        ),
        TechniqueFinishEvent(key="ocp", technique_name="OCP", e_ocp=0.123, csv_path="a.csv", dta_path="a.dta"),
        TechniqueErrorEvent(key="ocp", technique_name="OCP", error="ValueError('boom')"),
    ],
)
def test_kind_discriminator_round_trips_to_concrete_type(event):
    restored = parse_workflow_event(dump_workflow_event(event))
    assert type(restored) is type(event)
    assert restored.kind == event.kind


def test_parse_workflow_event_from_bare_dict():
    restored = parse_workflow_event({"kind": "technique_finish", "key": "eis", "technique_name": "EIS", "e_ocp": 0.0})
    assert isinstance(restored, TechniqueFinishEvent)
    assert restored.key == "eis"


def test_workflow_emitter_fans_out_by_exact_event_type():
    emitter = WorkflowEmitter()
    progress_seen = []
    finish_seen = []

    @emitter.on(TechniqueProgressEvent)
    def _on_progress(event):
        progress_seen.append(event)

    emitter.on(TechniqueFinishEvent)(finish_seen.append)

    progress = TechniqueProgressEvent(
        key="ocp", technique_name="OCP", data=_structured_curve(), elapsed_s=0.0, estimated_time_left=None
    )
    finish = TechniqueFinishEvent(key="ocp", technique_name="OCP", e_ocp=0.0)

    emitter.emit(progress)
    emitter.emit(finish)

    assert progress_seen == [progress]
    assert finish_seen == [finish]


def test_workflow_emitter_with_no_listeners_is_a_noop():
    WorkflowEmitter().emit(TechniqueStartEvent(key="ocp", technique_name="OCP"))
