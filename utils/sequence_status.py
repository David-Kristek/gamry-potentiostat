from potentiostat.core.workflow.emitter import (
    WorkflowEvent,
    TechniqueProgressEvent,
    TechniqueFinishEvent,
    TechniqueErrorEvent,
)
from pydantic import BaseModel
from enum import Enum
from concurrent.futures import Future
from pyproc_bridge import AbortError
from typing import Callable
from potentiostat.utils import throttle
from potentiostat.utils.technique_keys import base_technique
from potentiostat.core.workflow.emitter import WorkflowEmitter
import time


RAW_FIELDS = {
    "ocp": {"x": "time", "y": "vf", "xlabel": "Time (s)", "ylabel": "Eoc (V)"},
    "lpr": {"x": "vf", "y": "im", "xlabel": "Potential (V)", "ylabel": "Current (A)"},
    "cpp": {"x": "vf", "y": "im", "xlabel": "Potential (V)", "ylabel": "Current (A)"},
}


# TODO make faster using tolist
def _plot_payload(name: str, data) -> dict | None:
    if data is None or len(data) == 0:
        return None
    if name == "eis":
        zreal = [float(v) for v in data["zreal"]]
        zimag = [float(v) for v in data["zimag"]]
        freq = [float(v) for v in data["zfreq"]]
        return {
            "nyquist": {"x": zreal, "y": [-v for v in zimag]},
            "bode_mag": {"x": freq, "y": [float(v) for v in data["zmod"]]},
            "bode_phase": {"x": freq, "y": [float(v) for v in data["zphz"]]},
        }
    fields = RAW_FIELDS.get(name)
    if fields is None:
        return None
    return {
        "x": [float(v) for v in data[fields["x"]]],
        "y": [float(v) for v in data[fields["y"]]],
        "xlabel": fields["xlabel"],
        "ylabel": fields["ylabel"],
    }


class SequencePhase(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"
    STOPPED = "stopped"


class CurrentTechniqueStatus(BaseModel):
    technique: str
    plot: dict | None = None
    elapsed_s: float | None = None
    estimated_time_left: float | None = None

    @property
    def fraction_complete(self) -> float | None:
        if self.elapsed_s is not None and self.estimated_time_left is not None:
            total_time = self.elapsed_s + self.estimated_time_left
            if total_time > 0:
                return self.elapsed_s / total_time
        return None


class SequenceRunStatus(BaseModel):
    phase: SequencePhase = SequencePhase.PENDING
    technique_keys: list[str]
    sequenec_start_s: float
    sequence_end_s: float | None = None
    outdir: str
    technique_index: int = -1
    extra: str | None = None
    current_technique: CurrentTechniqueStatus | None = None

    @property
    def time_elapsed_s(self) -> float | None:
        if self.sequence_end_s is not None:
            return self.sequence_end_s - self.sequenec_start_s
        return time.monotonic() - self.sequenec_start_s


# TODO task based execution
class SequenceStatusTracker:
    def __init__(
        self,
        technique_keys: list[str],
        outdir: str,
        emitter: WorkflowEmitter,
        on_status: Callable[[SequenceRunStatus], None] | None = None,
        emit_interval_s: float = 0.5,
    ):
        self.status = SequenceRunStatus(
            phase=SequencePhase.PENDING,
            technique_keys=technique_keys,
            sequenec_start_s=time.monotonic(),
            outdir=outdir,
        )
        self.on_status = on_status or (lambda status: None)

        emitter.on(TechniqueProgressEvent)(throttle(emit_interval_s)(self._update_progress))
        emitter.on(TechniqueFinishEvent)(self._update_finish)
        emitter.on(TechniqueErrorEvent)(self._update_finish)

    def _update_progress(self, event: TechniqueProgressEvent):
        self.status.phase = SequencePhase.RUNNING
        self.status.technique_index = self.status.technique_keys.index(event.key)
        self.status.current_technique = CurrentTechniqueStatus(
            technique=event.technique_name,
            plot=_plot_payload(base_technique(event.key), event.data),
            elapsed_s=event.elapsed_s,
            estimated_time_left=event.estimated_time_left,
        )
        self.status.extra = f"{len(event.data)} point(s) collected"
        self.on_status(self.status)

    def _update_finish(self, event: TechniqueFinishEvent | TechniqueErrorEvent):
        self.status.technique_index = self.status.technique_keys.index(event.key)

        previous = self.status.current_technique
        self.status.current_technique = CurrentTechniqueStatus(
            technique=event.technique_name,
            elapsed_s=previous.elapsed_s if previous else None,
            estimated_time_left=0.0,
        )

        if isinstance(event, TechniqueFinishEvent):
            self.status.phase = SequencePhase.RUNNING
            self.status.extra = "done"
        else:
            self.status.phase = SequencePhase.ERROR
            self.status.extra = f"error: {event.error}"
        self.on_status(self.status)

    def update_by_event(self, event: WorkflowEvent):
        if isinstance(event, TechniqueProgressEvent):
            self._update_progress(event)
        elif isinstance(event, (TechniqueFinishEvent, TechniqueErrorEvent)):
            self._update_finish(event)

    def _finish(self, phase: SequencePhase, extra: str):
        self.status.phase = phase
        self.status.extra = extra
        self.status.sequence_end_s = time.monotonic()
        self.on_status(self.status)

    def watch(self, future: Future):
        """Push the final done/stopped/error status once `future` settles."""

        def _on_done(fut: Future):
            try:
                fut.result()
            except AbortError:
                self.sequence_abort()
            except Exception as exc:
                self.sequence_error(str(exc))
            else:
                self.sequence_done()

        future.add_done_callback(_on_done)

    def sequence_done(self):
        self._finish(SequencePhase.DONE, "done")

    def sequence_error(self, error: str):
        self._finish(SequencePhase.ERROR, f"error: {error}")

    def sequence_abort(self):
        self._finish(SequencePhase.STOPPED, "stop requested")

    def get_snapshot(self) -> SequenceRunStatus:
        return self.status.model_copy()


def parse_sequence_status(event: dict) -> SequenceRunStatus:
    return SequenceRunStatus.model_validate(event)
