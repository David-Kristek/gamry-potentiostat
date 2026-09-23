"""Workflow telemetry: the events a running sequence emits, plus a small
type-keyed fan-out helper for hosts that want several independent subscribers.

The measurement layer itself depends only on a plain
``Callable[[WorkflowEvent], None]`` sink -- ``WorkflowEmitter`` and the IPC
transport are just two things you can point that sink at.
"""

from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Type,
    TypeVar,
    Union,
)

try:  # Annotated/Literal are stdlib from 3.9/3.8; the Gamry Python is 3.7
    from typing import Annotated, Literal
except ImportError:
    from typing_extensions import Annotated, Literal

import numpy as np
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    PlainValidator,
    TypeAdapter,
)

if TYPE_CHECKING:  # runtime import is lazy (in technique_cls) to break a techniques <-> workflow cycle
    from potentiostat.core.techniques.technique import Technique

T = TypeVar("T", bound=BaseModel)


# --- Events -----------------------------------------------------------------


class WorkflowEvent(BaseModel):
    """Base for sequence telemetry. Every concrete event carries a distinct
    ``kind`` literal, so the union parses itself from a bare ``model_dump``
    with no registry -- see :func:`parse_workflow_event`."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    kind: str
    key: str
    technique_name: str

    @property
    def technique_cls(self) -> "Type[Technique]":
        from potentiostat.core.techniques.technique import Technique

        return Technique.from_key(self.key)


class TechniqueStartEvent(WorkflowEvent):
    kind: Literal["technique_start"] = "technique_start"


def _dump_ndarray(arr: np.ndarray) -> Any:
    """Plain `.tolist()` turns each row of a structured array (e.g. the
    curve data technique modules emit, with named fields like "time"/"vf")
    into a bare tuple, silently dropping the field names -- so the receiving
    side reconstructs a plain unnamed array and any later `data["time"]`
    field-name lookup raises. Keep the field names alongside the rows so
    `_load_ndarray` can rebuild the same structured dtype on the other end
    of the IPC hop."""
    arr = np.asarray(arr)
    if arr.dtype.names:
        return {"fields": list(arr.dtype.names), "rows": arr.tolist()}
    return arr.tolist()


def _load_ndarray(v: Any) -> np.ndarray:
    if isinstance(v, dict) and "fields" in v and "rows" in v:
        dtype = [(name, "f8") for name in v["fields"]]
        return np.array([tuple(row) for row in v["rows"]], dtype=dtype)
    return np.asarray(v)


# Order matters: PlainValidator must precede PlainSerializer in the metadata
# list, otherwise it replaces the core schema and the serializer is dropped
# (pydantic then fails to JSON-encode the raw ndarray).
NDArray = Annotated[
    np.ndarray,
    PlainValidator(_load_ndarray),
    PlainSerializer(_dump_ndarray, return_type=Any),
]


class TechniqueProgressEvent(WorkflowEvent):
    kind: Literal["technique_progress"] = "technique_progress"
    data: NDArray
    elapsed_s: float
    estimated_time_left: Optional[float]


class TechniqueFinishEvent(WorkflowEvent):
    kind: Literal["technique_finish"] = "technique_finish"
    e_ocp: float
    csv_path: Optional[str] = None
    dta_path: Optional[str] = None


class TechniqueErrorEvent(WorkflowEvent):
    kind: Literal["technique_error"] = "technique_error"
    error: str  # repr(exc) -- kept a plain string so the event stays JSON-safe


AnyWorkflowEvent = Annotated[
    Union[
        TechniqueStartEvent,
        TechniqueProgressEvent,
        TechniqueFinishEvent,
        TechniqueErrorEvent,
    ],
    Field(discriminator="kind"),
]

_event_adapter: TypeAdapter[WorkflowEvent] = TypeAdapter(AnyWorkflowEvent)


def parse_workflow_event(payload: Dict[str, Any]) -> WorkflowEvent:
    """Rebuild the concrete ``WorkflowEvent`` from its ``model_dump`` form,
    dispatching on the ``kind`` discriminator."""
    return _event_adapter.validate_python(payload)


def dump_workflow_event(event: WorkflowEvent) -> Dict[str, Any]:
    """JSON-safe ``dict`` form of an event, ready for the IPC wire."""
    return event.model_dump(mode="json")


# --- Host-side fan-out -----------------------------------------------------


class WorkflowEmitter:
    """Type-keyed multi-listener dispatch.

    Optional: use it when a host process has several independent subscribers
    for the same event (e.g. a live plot panel *and* a logger). Pass
    ``WorkflowEmitter().emit`` wherever a ``Callable[[WorkflowEvent], None]``
    sink is expected.
    """

    def __init__(self) -> None:
        self._listeners: Dict[Type[BaseModel], List[Callable]] = {}

    def on(self, event_type: Type[T]) -> Callable[[Callable[[T], None]], Callable[[T], None]]:
        def decorator(func: Callable[[T], None]) -> Callable[[T], None]:
            self._listeners.setdefault(event_type, []).append(func)
            return func

        return decorator

    def emit(self, event: BaseModel) -> None:
        for listener in self._listeners.get(type(event), []):
            listener(event)
