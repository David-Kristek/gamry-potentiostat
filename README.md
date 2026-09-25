# potentiostat

Run measurement sequences on a Gamry potentiostat via ToolkitPy.

Ships four techniques -- **OCP, EIS, LPR, CPP** -- and runs any ordered
combination of them (a sequence must start with `ocp`). Custom techniques plug
into the same loop.

## Setup

ToolkitPy only installs into Gamry's 32-bit Python 3.7, so this package is
split so a normal interpreter can drive it (see
[docs/architecture.md](docs/architecture.md)).

```powershell
uv sync --extra dev
Copy-Item .env.example .env   # fill in paths if auto-detection fails
```

`.env` keys: `GAMRY_PYTHON`, `TOOLKITPY_HOME`, `GAMRY_SOURCE_ROOT` -- all
optional. Details in [docs/configuration.md](docs/configuration.md).

## Run from any interpreter

`run_sequence` spawns the Gamry Python as an IPC worker and streams events back.

```python
from pyproc_bridge import AbortSignal
from potentiostat import ExecuteSequenceConfig, SequenceConfig
from potentiostat.gamry_potentiostat.runner import run_sequence

cfg = ExecuteSequenceConfig(
    technique_keys=["ocp", "eis", "lpr", "cpp"],
    outdir="./run_output",
    config=SequenceConfig(),  # edit fields for a real run
)

run = run_sequence(cfg, on_event=print, abort=AbortSignal())
results = run.result()  # blocks; re-raises on failure
for key, outcome in results.items():
    print(key, outcome.csv_path)
```

## Run directly under the Gamry Python

Skip the subprocess if you are already on the Gamry 3.7 interpreter:

```python
from pyproc_bridge import AbortSignal
from potentiostat import ExecuteSequenceConfig, SequenceConfig, execute_sequence_sync

cfg = ExecuteSequenceConfig(technique_keys=["ocp", "eis"], outdir="./run_output", config=SequenceConfig())
results = execute_sequence_sync(cfg, abort=AbortSignal())
```

## Add a technique

Subclass `Technique` and set `name` -- it auto-registers and the sequence loop
picks it up. Expose its config on a `SequenceConfig` subclass under the same
name:

```python
from pydantic import Field
from potentiostat import ExecuteSequenceConfig, SequenceConfig, execute_sequence
from potentiostat.core.techniques import Technique
from potentiostat.parsing.sequence_config import GamryBaseConfig


class HoldConfig(GamryBaseConfig):
    voltage_v: float = 0.1
    total_time_s: float = 30.0


class Hold(Technique[HoldConfig]):
    name = "hold"
    col_mapping = {"time": "Time (s)", "vf": "Voltage (V)"}

    def _initialize(self, ctx): ...  # set the control mode
    def _measure(self, ctx): ...  # acquire the curve, write the .DTA, return (result, e_ocp)


class MySequenceConfig(SequenceConfig):
    hold: HoldConfig = Field(default_factory=HoldConfig)


cfg = ExecuteSequenceConfig(technique_keys=["ocp", "hold", "eis"], outdir="./run_output", config=MySequenceConfig())
print(execute_sequence(cfg).result())
```

More in [docs/techniques.md](docs/techniques.md); runnable references in
[`examples/`](examples/).

## Docs

| Doc | Covers |
|---|---|
| [architecture.md](docs/architecture.md) | the two-interpreter split, IPC, module map |
| [techniques.md](docs/techniques.md) | the four techniques, configs, adding your own |
| [configuration.md](docs/configuration.md) | `.env`, `SequenceConfig`, `.GSequence` |

## Development

```powershell
uv run --extra dev ruff format .
uv run --extra dev ruff check .
```

## License

MIT -- see [LICENSE](LICENSE).
