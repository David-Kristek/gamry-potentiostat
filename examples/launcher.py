"""64-bit host: launch the sequence in the Gamry 32-bit Python as a
subprocess, stream its events back over IPC, and show a live plot.

Run this with ANY interpreter (it never imports ToolkitPy). It needs the
Gamry Python located via the environment:

    set GAMRY_PYTHON=C:\\...\\Gamry Instruments\\...\\python.exe
    python -m examples.launcher

`run_sequence` runs on a side thread by default and returns a `Future`
immediately -- `future.result(timeout=...)` blocks for the outcome (or
re-raises whatever the run failed with). So the main thread is free the whole
time to own matplotlib -- required, since only the main thread may touch a
figure's canvas.

Event wiring
------------
All host-side listeners are decorators on a single `WorkflowEmitter`. Events
arrive from the IPC reader thread and are dispatched straight to every
listener from there -- `LivePanel`'s own listener only mutates line data
under a lock; it never draws (see plotting/live_panel.py). The other
listeners below just print, which is thread-safe.
"""

from __future__ import annotations

import concurrent.futures as futures
import os

import matplotlib.pyplot as plt

from potentiostat.gamry_potentiostat.runner import run_sequence
from potentiostat.core.sequence import ExecuteSequenceConfig
from potentiostat.parsing.sequence_config import SequenceConfig
from pyproc_bridge import AbortSignal, AbortError
from potentiostat.core.workflow.emitter import (
    TechniqueStartEvent,
    TechniqueProgressEvent,
    TechniqueFinishEvent,
    TechniqueErrorEvent,
    WorkflowEmitter,
)
from potentiostat.plotting.live_panel import LivePanel

OUT_DIR = "./run_output"

# --- listeners: decorator style, as many as you like ----------------------

emitter = WorkflowEmitter()


@emitter.on(TechniqueStartEvent)
def _on_start(e: TechniqueStartEvent) -> None:
    print(f">> {e.key}")


@emitter.on(TechniqueProgressEvent)
def _on_progress(e: TechniqueProgressEvent) -> None:
    print(f"   {e.key}: {len(e.data)} pts", end="\r")


@emitter.on(TechniqueFinishEvent)
def _on_finish(e: TechniqueFinishEvent) -> None:
    print(f"[ok]  {e.key}   E_oc = {e.e_ocp:+.4f} V   -> {e.csv_path}")


@emitter.on(TechniqueErrorEvent)
def _on_error(e: TechniqueErrorEvent) -> None:
    print(f"[ERR] {e.key}: {e.error}")


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)

    cfg = ExecuteSequenceConfig(
        technique_keys=["ocp", "eis", "lpr", "cpp"],  # must start with "ocp"
        outdir=OUT_DIR,
        config=SequenceConfig(),
        pstat_name=None,
    )

    abort = AbortSignal()
    future = run_sequence(cfg, emitter.emit, abort)  # side thread by default
    # run_future wires the window to close itself the instant an early
    # failure happens, instead of blocking on plt.show() until closed by hand
    _panel = LivePanel(emitter, run_future=future)  # opens the window, wires its own listener; keep referenced

    try:
        plt.show()  # blocks main thread on the GUI mainloop until closed
    except KeyboardInterrupt:
        print("\naborting...")
        abort.abort("keyboard interrupt")

    # window closed (or Ctrl-C) doesn't itself stop the run -- give it a
    # bounded grace period to actually finish before this exits
    try:
        results = future.result(timeout=15.0)
    except AbortError:
        print("\nrun aborted")
    except futures.TimeoutError:
        print("\n(worker still shutting down in the background)")
    else:
        print("\nsequence complete:")
        for key in results:
            print(f"  {key}: {results[key].csv_path}")


if __name__ == "__main__":
    main()
