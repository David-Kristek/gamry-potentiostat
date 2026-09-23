from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import partial
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Generic,
    List,
    Optional,
    TypeVar,
)

from pydantic import BaseModel, RootModel

if TYPE_CHECKING:
    from potentiostat.plotting.technique_plots import TechniquePlotter

try:  # TypedDict/ClassVar are stdlib from 3.8; the Gamry Python is 3.7
    from typing import ClassVar, Optional, TypedDict
except ImportError:
    from typing_extensions import ClassVar, Optional, TypedDict
import os

import numpy as np
import numpy.typing as npt
import pandas as pd
from pyproc_bridge import AbortError, AbortSignal

from potentiostat.core.workflow.emitter import (
    TechniqueErrorEvent,
    TechniqueFinishEvent,
    TechniqueProgressEvent,
    TechniqueStartEvent,
    WorkflowEvent,
)
from potentiostat.parsing.sequence_config import GamryBaseConfig, SequenceConfig
from potentiostat.utils import throttle
from potentiostat.utils.technique_keys import base_technique

ConfigT = TypeVar("ConfigT", bound=GamryBaseConfig)

TechniqueData = npt.NDArray[np.void]


class _TechniqueResultRequired(TypedDict):
    data: "TechniqueData"  # raw structured curve; consumed in-process by write_csv
    dta_path: str
    csv_path: str


class TechniqueResult(_TechniqueResultRequired, total=False):
    legs: list[str]  # CPP only: per-row forward/reverse leg tag for the CSV


class TechniqueOutcome(BaseModel):
    """The JSON-safe slice of a TechniqueResult that survives the IPC hop back
    to the caller: the artefact paths only. The raw `data` array never leaves
    the worker process."""

    dta_path: str
    csv_path: str
    # List[...]/Optional[...]: pydantic evaluates this eagerly even under
    # `from __future__ import annotations`, and the Gamry Python is 3.7.
    legs: Optional[List[str]] = None


class SequenceResults(RootModel[Dict[str, TechniqueOutcome]]):
    """``{technique key -> artefact paths}`` for one executed sequence."""

    def __iter__(self):
        return iter(self.root)

    def __getitem__(self, key: str) -> TechniqueOutcome:
        return self.root[key]

    def items(self):
        return self.root.items()


Estimator = Optional[Callable[[float, int, int], Optional[float]]]


class TechniqueTime:
    def __init__(self, estimator: Estimator = None, total_points: int = 0):
        self._estimator = estimator
        self.start_time: float | None = None
        self.elapsed_s: float = 0.0
        self.total_points: int = total_points

    def start(self) -> None:
        self.elapsed_s = 0.0
        self.start_time = time.monotonic()

    def update(self) -> float:
        if self.start_time is None:
            raise RuntimeError("TechniqueTime.update() called before start()")
        self.elapsed_s = time.monotonic() - self.start_time
        return self.elapsed_s

    def get_estimated_time_left(self, total_steps: int) -> float | None:
        if self._estimator is None:
            return None
        return self._estimator(self.elapsed_s, total_steps, self.total_points)


class TechniqueEmitter:
    def __init__(
        self,
        key: str,
        technique_name: str,
        on_event: Callable[[WorkflowEvent], None],
        time: TechniqueTime,
        abort: AbortSignal | None = None,
    ):
        self.key = key
        self.technique_name = technique_name
        self._on_event = on_event
        self._abort = abort
        self.time = time

    def emit_start(self) -> None:
        self._on_event(TechniqueStartEvent(key=self.key, technique_name=self.technique_name))
        self.time.start()

    @throttle(0.5)
    def emit_progress(self, data: TechniqueData) -> None:
        self.time.update()

        points_collected = len(data) if data is not None else 0
        remaining_s = self.time.get_estimated_time_left(points_collected)
        self._on_event(
            TechniqueProgressEvent(
                key=self.key,
                technique_name=self.technique_name,
                data=data,
                elapsed_s=self.time.elapsed_s,
                estimated_time_left=remaining_s,
            )
        )

    def emit_finish(self, result: TechniqueResult, new_e_ocp: float) -> None:
        self._on_event(
            TechniqueFinishEvent(
                key=self.key,
                technique_name=self.technique_name,
                csv_path=result["csv_path"],
                dta_path=result["dta_path"],
                e_ocp=new_e_ocp,
            )
        )

    def fail(self, exc: Exception) -> None:
        self._on_event(TechniqueErrorEvent(key=self.key, technique_name=self.technique_name, error=repr(exc)))
        if self._abort is not None:
            self._abort.abort(exc)


@dataclass(frozen=True)
class TechniqueContext(Generic[ConfigT]):
    key: str
    technique_name: str
    cfg: ConfigT
    e_ocp: float
    outdir: str
    pstat: Any
    tkp: Any
    emitter: TechniqueEmitter
    abort: AbortSignal | None = None

    @property
    def csv_path(self) -> str:
        return os.path.join(self.outdir, f"{self.key}.csv")

    @property
    def dta_path(self) -> str:
        return os.path.join(self.outdir, f"{self.key}.dta")

    @classmethod
    def from_sequence(
        cls,
        key: str,
        tkp: Any,
        pstat: Any,
        config: SequenceConfig,
        technique_name: str,
        e_ocp: float,
        outdir: str,
        on_event: Callable[[WorkflowEvent], None] = lambda _event: None,
        abort: AbortSignal | None = None,
    ) -> TechniqueContext[ConfigT]:
        technique_cls = Technique.get(technique_name)
        cfg = getattr(config, technique_name)
        timer = TechniqueTime(
            estimator=partial(technique_cls.estimate_remaining_time, cfg),
            total_points=technique_cls.estimated_total_points(cfg) or 0,
        )

        emitter = TechniqueEmitter(
            key=key,
            technique_name=technique_name,
            on_event=on_event,
            time=timer,
            abort=abort,
        )
        return cls(
            key=key,
            technique_name=technique_name,
            cfg=cfg,
            e_ocp=e_ocp,
            outdir=outdir,
            pstat=pstat,
            tkp=tkp,
            emitter=emitter,
            abort=abort,
        )


class Technique(ABC, Generic[ConfigT]):
    name: ClassVar[str]
    _registry: ClassVar[dict[str, Technique]] = {}
    # keys are names in numpy array, values are new column labels for Pandas Dataframe
    col_mapping: ClassVar[dict] = {}
    # This technique's visualizer (see plotting/technique_plots.py); None = no plot.
    plotter: ClassVar[type[TechniquePlotter] | None] = None

    def __init_subclass__(cls, **kwargs: Any) -> None:

        super().__init_subclass__(**kwargs)
        if not getattr(cls, "name", None):
            return

        Technique._registry[cls.name] = cls

    @classmethod
    def get(cls, name: str) -> Technique:
        if name not in cls._registry:
            raise ValueError(f"Technique '{name}' is not registered")
        return cls._registry[name]

    @classmethod
    def from_key(cls, key: str) -> Technique:
        return cls._registry[base_technique(key)]

    @classmethod
    def all_techniques(cls) -> dict[str, Technique]:
        return dict(cls._registry)

    def run(self, ctx: TechniqueContext[ConfigT]) -> tuple[TechniqueResult, float]:
        """Run one technique against live hardware: telemetry, analog setup,
        the measurement itself, then the CSV export. The .DTA is written inside
        measure() -- it needs technique-specific parameters this template
        can't carry."""
        ctx.emitter.emit_start()
        try:
            self._initialize(ctx)
            result, new_e_ocp = self._measure(ctx)
            self.write_csv(ctx.csv_path, result)
        except (KeyboardInterrupt, AbortError):
            raise
        except Exception as exc:
            ctx.emitter.fail(exc)
            raise

        ctx.emitter.emit_finish(result, new_e_ocp)
        return result, new_e_ocp

    def __call__(self, ctx: TechniqueContext[ConfigT]) -> tuple[TechniqueResult, float]:
        """Convenience: run() is the public API, but this lets a Technique
        instance be called directly as a function."""
        return self.run(ctx)

    @abstractmethod
    def _initialize(self, ctx: TechniqueContext[ConfigT]) -> None:
        """Put the instrument into the right control mode for this technique."""

    @abstractmethod
    def _measure(self, ctx: TechniqueContext[ConfigT]) -> tuple[TechniqueResult, float]:
        """Configure the signal, acquire the curve, write the .DTA, and return
        the result dict plus the Eoc to carry into the next technique."""

    def to_dataframe(self, data: TechniqueData, **kwargs) -> pd.DataFrame:
        for key in self.col_mapping.keys():
            if key not in data.dtype.names:
                raise ValueError(f"Key '{key}' not found in data dtype names: {data.dtype.names}")
        return pd.DataFrame({new_col: data[key] for key, new_col in self.col_mapping.items()})

    def to_dta(self, data: TechniqueData, path: str) -> None:
        """The .DTA is written during measure(), which still has the technique
        parameters ToolkitPy's writers need; regenerating it from `data` alone
        is not supported."""
        raise NotImplementedError(f"{type(self).__name__}.to_dta: .DTA is written during measure()")

    def write_csv(self, path: str, result: TechniqueResult) -> None:
        self.to_dataframe(result["data"]).to_csv(path, index=False)

    @classmethod
    def get_empty_df(cls) -> pd.DataFrame:
        """A zero-row frame shaped like to_dataframe's output, to seed empty
        plot lines before a run starts."""
        return pd.DataFrame({col: [] for col in cls.col_mapping.values()})

    def save_figure(self, out_dir: str, df: pd.DataFrame, run_id: str) -> str | None:
        """Delegate to the plotter, if this technique has one."""
        if self.plotter is None:
            return None
        return self.plotter.save_figure(out_dir, df, run_id, self.name)

    @staticmethod
    def estimated_total_duration_s(cfg: ConfigT) -> Optional[float]:
        """Override alone for a fixed-rate ramp/hold technique (OCP/LPR/CPP do);
        estimated_total_points/estimate_remaining_time both derive from it. Default None
        means duration isn't knowable ahead of time (e.g. EIS) -- override
        estimated_total_points directly instead in that case."""
        return None

    @classmethod
    def estimated_total_points(cls, cfg: ConfigT) -> Optional[int]:
        duration_s = cls.estimated_total_duration_s(cfg)
        sample_time_s = getattr(cfg, "sample_time_s", None)
        if duration_s is None or not sample_time_s:
            return None
        return max(1, int(duration_s / max(sample_time_s, 1e-6)))

    @classmethod
    def estimate_remaining_time(
        cls, cfg: ConfigT, elapsed_s: float, points_collected: int, total_points: int
    ) -> Optional[float]:
        duration_s = cls.estimated_total_duration_s(cfg)
        if duration_s is not None:
            return max(0.0, duration_s - elapsed_s)

        # No analytic duration: extrapolate linearly from the points-per-second rate seen so far.
        if points_collected <= 0 or total_points <= 0:
            return None
        points_left = total_points - points_collected
        if points_left <= 0:
            return 0.0
        return (elapsed_s / points_collected) * points_left
