from potentiostat.core.workflow.emitter import (
    WorkflowEvent,
    TechniqueProgressEvent,
    TechniqueFinishEvent,
    TechniqueErrorEvent,
)
from pydantic import BaseModel, Field
from enum import Enum
from concurrent.futures import Future
from pyproc_bridge import AbortError
from typing import Callable
from potentiostat.utils import throttle
from potentiostat.utils.technique_keys import base_technique
from potentiostat.core.workflow.emitter import WorkflowEmitter
import math
import time


# Axis labels mirror potentiostat/plotting/technique_plots.py so the plotted
# payload and the saved/live matplotlib figures agree. CPP is not a plain field
# pair -- its plotter puts log|I| on x and potential on y -- so it is handled
# separately in _plot_payload.
RAW_FIELDS = {
    "ocp": {"x": "time", "y": "vf", "xlabel": "Time (s)", "ylabel": "OCP (V)"},
    "lpr": {"x": "vf", "y": "im", "xlabel": "Potential (V)", "ylabel": "Current (A)"},
}


def _log_abs(value) -> float | None:
    """log10|value|, or None where the magnitude is zero / not finite (a gap)."""
    magnitude = abs(float(value))
    return math.log10(magnitude) if magnitude > 0 else None


# Each curve in the pushed payload is capped here. The server replaces its
# whole snapshot on every push (no merge), so without a cap a long OCP curve
# would be re-uploaded every emit_interval_s for the rest of the sequence.
# Only this display payload is thinned -- the saved CSV/DTA data is untouched.
MAX_PLOT_POINTS = 1000


def _thin_pair(x: list, y: list, max_points: int = MAX_PLOT_POINTS) -> tuple[list, list]:
    step = max(1, math.ceil(len(x) / max_points))
    return (x[::step], y[::step]) if step > 1 else (x, y)


def _thin_xy(payload: dict, max_points: int) -> dict:
    x, y = payload.get("x"), payload.get("y")
    if x is None or y is None:
        return payload
    x, y = _thin_pair(x, y, max_points)
    return {**payload, "x": x, "y": y}


def _thin_payload(payload: dict | None, max_points: int = MAX_PLOT_POINTS) -> dict | None:
    if payload is None:
        return None
    if "nyquist" in payload:  # EIS: each sub-panel is its own {x, y}
        return {name: _thin_xy(part, max_points) for name, part in payload.items()}
    return _thin_xy(payload, max_points)


# TODO make faster using tolist
def _build_plot_payload(name: str, data) -> dict | None:
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
    if name == "cpp":
        return {
            "x": [_log_abs(v) for v in data["im"]],
            "y": [float(v) for v in data["vf"]],
            "xlabel": "log|I| (A)",
            "ylabel": "Potential (V)",
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


def _plot_payload(name: str, data) -> dict | None:
    """JSON plot for `name`, thinned to `MAX_PLOT_POINTS` per curve."""
    return _thin_payload(_build_plot_payload(name, data))


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
    plots: dict[str, dict] = Field(default_factory=dict)

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
        self._push = throttle(emit_interval_s)(self._notify)

        emitter.on(TechniqueProgressEvent)(self._update_progress)
        emitter.on(TechniqueFinishEvent)(self._update_finish)
        emitter.on(TechniqueErrorEvent)(self._update_finish)

    def _notify(self):
        self.on_status(self.status)

    def _update_progress(self, event: TechniqueProgressEvent):
        payload = _plot_payload(base_technique(event.key), event.data)
        if payload is not None:
            self.status.plots[event.key] = payload
        self.status.phase = SequencePhase.RUNNING
        self.status.technique_index = self.status.technique_keys.index(event.key)
        self.status.current_technique = CurrentTechniqueStatus(
            technique=event.technique_name,
            plot=payload,
            elapsed_s=event.elapsed_s,
            estimated_time_left=event.estimated_time_left,
        )
        self.status.extra = f"{len(event.data)} point(s) collected"
        self._push()

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
        self._notify()

    def update_by_event(self, event: WorkflowEvent):
        if isinstance(event, TechniqueProgressEvent):
            self._update_progress(event)
        elif isinstance(event, (TechniqueFinishEvent, TechniqueErrorEvent)):
            self._update_finish(event)

    def _finish(self, phase: SequencePhase, extra: str):
        self.status.phase = phase
        self.status.extra = extra
        self.status.sequence_end_s = time.monotonic()
        self._notify()

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
        return self.status.model_copy(deep=True)


def parse_sequence_status(event: dict) -> SequenceRunStatus:
    return SequenceRunStatus.model_validate(event)
