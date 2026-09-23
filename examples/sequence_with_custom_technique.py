"""Run the full built-in sequence pipeline (`core.sequence.execute_sequence`
-- the same one examples/run_measurement.py uses: ocp-first loop, side
thread, `Future[SequenceResults]`) with a custom technique mixed in alongside
the built-in ones.

`execute_sequence_sync` looks up each technique's config via
`getattr(sequence_config, technique_name)` -- `SequenceConfig` only defines
ocp/eis/lpr/cpp, since it mirrors the fixed set of techniques a real
.GSequence file can contain (see parsing/sequence_config.py). A one-off
technique like `Hold` (examples/add_technique.py) isn't part of that file
format, so it isn't a `SequenceConfig` field -- but `SequenceConfig` is a
plain pydantic model, so subclassing it locally to add one is enough to make
`execute_sequence`'s loop treat "hold" exactly like a built-in technique,
with no changes to the shared parsing/sequence_config.py.

Run under the Gamry 32-bit Python:

    "C:/.../Gamry Instruments/.../python.exe" -m examples.sequence_with_custom_technique
"""

from __future__ import annotations

import os

from pydantic import Field

from potentiostat.core.sequence import ExecuteSequenceConfig, execute_sequence
from potentiostat.core.workflow.emitter import WorkflowEvent
from examples.add_technique import HoldConfig  # noqa: F401 -- import registers "hold"
from potentiostat.parsing.sequence_config import SequenceConfig
from pyproc_bridge import AbortError

OUT_DIR = "./run_output"


class MySequenceConfig(SequenceConfig):
    """SequenceConfig plus the one-off "hold" technique from
    examples/add_technique.py -- a local subclass, not a change to the
    shared parsing/sequence_config.py, since "hold" isn't part of the real
    .GSequence file format that model mirrors."""

    hold: HoldConfig = Field(default_factory=HoldConfig)


def on_event(event: WorkflowEvent) -> None:
    print(f"[{event.kind}] {event.key}")


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)

    cfg = ExecuteSequenceConfig(
        technique_keys=["ocp", "hold", "eis"],  # must start with "ocp"
        outdir=OUT_DIR,
        config=MySequenceConfig(hold=HoldConfig(voltage_v=0.1, total_time_s=30.0)),
        pstat_name=None,
    )

    future = execute_sequence(cfg, on_event=on_event)  # runs on a side thread

    try:
        results = future.result()
    except AbortError:
        print("run aborted")
    else:
        print("sequence complete:")
        for key in results:
            print(f"  {key}: {results[key].csv_path}")


if __name__ == "__main__":
    main()
