"""
live_panel.py
-------------
Optional live matplotlib panel while a technique runs. Only touched when a
run asks for a live plot; matplotlib is imported here regardless.

Each panel's drawing and updating is delegated to the technique's plotter
(Technique.plotter -- see plotting/technique_plots.py): the dashboard only
lays out the shared figure's axes and dispatches progress data to the right
plotter's update.

Progress events can arrive from any thread (the caller is expected to run
the sequence on a side thread and keep the main thread free for matplotlib --
see examples/run_measurement.py). Only Artist data is mutated off the main
thread (locked); the canvas is only ever touched by `_redraw`, on a
FuncAnimation timer that matplotlib always fires on the main thread.

Pass the side-thread run's `Future` as `run_future` to also break a caller's
blocking `plt.show()` the instant that future fails, instead of leaving a
blank window open until it's closed by hand.
"""

from __future__ import annotations

import concurrent.futures as futures
import threading
from typing import Tuple

import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.lines import Line2D

from potentiostat.plotting.plot_style import INK, style_axes
from potentiostat.core.techniques.technique import Technique
from potentiostat.core.workflow.emitter import TechniqueProgressEvent, WorkflowEmitter


def get_default_axes() -> Tuple[dict[str, list[Axes]], Figure]:
    fig = plt.figure(figsize=(13, 7))
    gs = fig.add_gridspec(2, 3, hspace=0.4, wspace=0.35)
    return ({
        "ocp": [fig.add_subplot(gs[0, 0])],
        "lpr": [fig.add_subplot(gs[0, 1])],
        "cpp": [fig.add_subplot(gs[0, 2])],
        "eis": [fig.add_subplot(gs[1, 0]), fig.add_subplot(gs[1, 1:])],
    }, fig)


class LivePanel:
    """One matplotlib window, laid out once, with a panel per technique."""

    def __init__(
        self,
        emitter: WorkflowEmitter,
        fig: Figure | None = None,
        axes_dict: dict[str, list[Axes]] | None = None,
        redraw_interval_ms: int = 200,
        run_future: futures.Future | None = None,
    ) -> None:
        style_axes(plt, font_size=9)

        if axes_dict is None or fig is None:
            axes_dict, fig = get_default_axes()

        self.fig = fig
        self.axes_dict = axes_dict
        self.fig.suptitle("Live measurement", fontsize=12, color=INK)
        # RLock, not Lock: FuncAnimation's lazy first start re-enters _redraw
        # on this same thread (it hooks draw_event to self-start on the first
        # real draw), so the draw side must tolerate same-thread reentrancy.
        self._lock = threading.RLock()

        self.lines: dict[str, list[Line2D]] = {}
        for key, axes in axes_dict.items():
            plotter = Technique.from_key(key).plotter
            if plotter is None:
                continue
            empty_df = Technique.from_key(key).get_empty_df()
            self.lines[key] = plotter.plot_data(axes, empty_df, key.upper())

        @emitter.on(TechniqueProgressEvent)
        def on_progress(event: TechniqueProgressEvent) -> None:
            # callable from any thread: only mutates Artist data, under lock
            if event.key not in self.lines:
                return
            plotter = Technique.from_key(event.key).plotter
            if plotter is None:
                return
            with self._lock:
                plotter.update_lines(self.lines[event.key], event.data)

        # kept on self -- an unreferenced FuncAnimation is GC'd and stops ticking
        self._animation = FuncAnimation(
            self.fig, self._redraw, interval=redraw_interval_ms, cache_frame_data=False
        )

        if run_future is not None:
            # a failure before the first TechniqueStartEvent (bad env,
            # hardware not connecting, ...) never reaches on_progress, so
            # nothing above would otherwise touch the window -- poll the
            # future from this same main-thread GUI timer and close the
            # window the instant it fails, instead of leaving a blank plot
            # open until the caller's blocking plt.show() is closed by hand
            self._fail_timer = self.fig.canvas.new_timer(interval=redraw_interval_ms)
            self._fail_timer.add_callback(self._close_on_early_failure, run_future)
            self._fail_timer.start()

    def _close_on_early_failure(self, run_future: futures.Future) -> None:
        # only FuncAnimation/timers call this, on the main thread's GUI loop
        if run_future.done() and not run_future.cancelled() and run_future.exception() is not None:
            self._fail_timer.stop()
            plt.close(self.fig)

    def _redraw(self, _frame: int | None = None) -> None:
        # only FuncAnimation calls this, on the main thread's GUI timer
        with self._lock:
            self.fig.canvas.draw_idle()


_dashboard: LivePanel | None = None


def init_dashboard(
    emitter: WorkflowEmitter,
    fig: Figure | None = None,
    axes_dict: dict[str, list[Axes]] | None = None,
) -> LivePanel:
    """Return the process-wide live dashboard, creating its window on first use."""
    global _dashboard
    if _dashboard is None:
        _dashboard = LivePanel(emitter=emitter, fig=fig, axes_dict=axes_dict)
    return _dashboard
