"""Simplest possible run: one technique, synchronous, no plotting, no side
thread -- good for a quick hardware smoke test, or as the minimal building
block examples/custom_sequence.py and examples/add_technique.py start from.

Run under the Gamry 32-bit Python:

    "C:/.../Gamry Instruments/.../python.exe" -m examples.single_technique
"""

from __future__ import annotations

import os

from potentiostat.core.hardware.device import open_session
from potentiostat.core.techniques.technique import Technique, TechniqueContext
from potentiostat.parsing.sequence_config import SequenceConfig

OUT_DIR = "./run_output"
TECHNIQUE = "ocp"  # any of "ocp", "eis", "lpr", "cpp"


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    cfg = SequenceConfig()  # default parameters; edit its fields for a real run

    with open_session(None) as (tkp, pstat):
        ctx = TechniqueContext.from_sequence(
            key=TECHNIQUE,
            tkp=tkp,
            pstat=pstat,
            config=cfg,
            technique_name=TECHNIQUE,
            e_ocp=0.0,
            outdir=OUT_DIR,
        )
        result, e_ocp = Technique.get(TECHNIQUE)().run(ctx)

    print(f"{TECHNIQUE}: Eoc = {e_ocp:+.4f} V -> {result['csv_path']}")


if __name__ == "__main__":
    main()
