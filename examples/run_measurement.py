"""Standalone run: OCP -> EIS -> LPR -> CPP on a side thread, live plot on
the main thread.

Run this WITH the Gamry 32-bit Python (it calls into ToolkitPy directly):

    "C:/.../Gamry Instruments/.../python.exe" -m examples.run_measurement

No subprocess, no IPC (unlike examples/launcher.py) -- but `execute_sequence`
runs on a side thread by default and returns a `Future[SequenceResults]`
immediately, same convention as `run_sequence` in gamry_potentiostat/runner.py.
That leaves the main thread free for matplotlib -- required, since only the
main thread may touch a figure's canvas.

Event wiring
------------
`on_event=emitter.emit` fires from that side thread, so EVERY listener on
`emitter`, not just LivePanel's, runs there -- including the plain print()
listeners below. That's fine for them (printing is thread-safe and nothing
else prints concurrently); `LivePanel` is the only one touching matplotlib,
so it's the only one that needed care: its listener only mutates Artist data
under a lock, and a FuncAnimation timer -- which matplotlib always fires on
the main thread -- is what actually redraws.
"""

from __future__ import annotations

import concurrent.futures as futures
import os

import matplotlib.pyplot as plt

from potentiostat.core.sequence import ExecuteSequenceConfig, execute_sequence
from potentiostat.parsing.sequence_config import SequenceConfig
from pyproc_bridge import AbortSignal, AbortError
from potentiostat.core.workflow.emitter import (
    WorkflowEmitter,
    TechniqueStartEvent,
    TechniqueProgressEvent,
    TechniqueFinishEvent,
    TechniqueErrorEvent,
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
    future = execute_sequence(cfg, on_event=emitter.emit, abort=abort)  # side thread by default
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
        print("\n(sequence still shutting down in the background)")
    else:
        print("\nsequence complete:")
        for key in results:
            print(f"  {key}: {results[key].csv_path}")


if __name__ == "__main__":
    main()
