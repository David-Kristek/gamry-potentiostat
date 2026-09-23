"""
console_log.py
---------------
Minimal host-side console logger: wires start/finish/error print listeners
onto a WorkflowEmitter for callers that just want to see progress on stdout
(no live plot).
"""

from __future__ import annotations

from potentiostat.core.workflow.emitter import (
    TechniqueErrorEvent,
    TechniqueFinishEvent,
    TechniqueStartEvent,
    WorkflowEmitter,
)


def log_to_console(emitter: WorkflowEmitter) -> None:
    """Print a line per technique start/finish/error on `emitter`."""

    @emitter.on(TechniqueStartEvent)
    def _on_start(event: TechniqueStartEvent) -> None:
        print(f"  [{event.key}] started")

    @emitter.on(TechniqueFinishEvent)
    def _on_finish(event: TechniqueFinishEvent) -> None:
        print(f"  [{event.key}] done -> {event.csv_path}")

    @emitter.on(TechniqueErrorEvent)
    def _on_error(event: TechniqueErrorEvent) -> None:
        print(f"  [{event.key}] failed: {event.error}")
