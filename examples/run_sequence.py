"""Full sequence (OCP -> EIS -> LPR -> CPP) from any interpreter, with a live
matplotlib panel -- the recommended way to run a measurement.

`run_sequence` spawns the Gamry 32-bit Python as an IPC worker and streams
events back, so this process never imports ToolkitPy. The run goes on a side
thread and returns a Future immediately, leaving the main thread free for
matplotlib (only the main thread may touch a figure's canvas).

See examples/single_technique.py for a minimal direct run, examples/add_technique.py
for a custom technique, and examples/custom_sequence.py for custom control flow.

Run with any interpreter (the Gamry Python is located via .env -- see README):

    python -m examples.run_sequence
"""

from __future__ import annotations

import concurrent.futures as futures
import os

import matplotlib.pyplot as plt

from pyproc_bridge import AbortError, AbortSignal
from potentiostat import ExecuteSequenceConfig, SequenceConfig
from potentiostat.core.workflow.emitter import WorkflowEmitter
from potentiostat.gamry_potentiostat.runner import run_sequence
from potentiostat.plotting.live_panel import LivePanel
from potentiostat.utils import log_to_console

# Absolute so the worker (which runs with a different cwd) writes here too.
OUT_DIR = os.path.abspath("run_output")


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)

    cfg = ExecuteSequenceConfig(
        technique_keys=["ocp", "eis", "lpr", "cpp"],  # must start with "ocp"
        outdir=OUT_DIR,
        config=SequenceConfig(),
    )

    emitter = WorkflowEmitter()
    log_to_console(emitter)  # one line per technique start/finish/error

    abort = AbortSignal()
    future = run_sequence(cfg, emitter.emit, abort)

    # Opens the window and wires its own progress listener; keep it referenced.
    # run_future lets the window close itself the instant the run fails.
    _panel = LivePanel(emitter, run_future=future)

    try:
        plt.show()  # blocks the main thread until the window is closed
    except KeyboardInterrupt:
        print("\naborting...")
        abort.abort("keyboard interrupt")

    # Closing the window doesn't stop the run -- give it a bounded grace period.
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
