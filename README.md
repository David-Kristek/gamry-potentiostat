# potentiostat

Importable Python library that runs an **OCP → EIS → LPR → CPP** measurement
sequence on a Gamry potentiostat via ToolkitPy. Used standalone here and as the
measurement backend of the electrodeposition rig.

## Architecture

ToolkitPy only installs into Gamry's 32-bit Python 3.7
(`C:\Program Files (x86)\Gamry Instruments\Python\Python37-32\python.exe`).
So the package splits in two:

| Must run under Gamry 3.7 | Runs on any interpreter |
|---|---|
| `potentiostat.core` (hardware I/O, technique runners, sequence driver) | `potentiostat.parsing`, `potentiostat.plotting`, `potentiostat.utils`, `potentiostat.gamry_potentiostat` |

`gamry_potentiostat.runner.run_sequence()` spawns that interpreter as an IPC
worker (over the separate `pyproc-bridge` package), so a normal 64-bit host can
run a measurement without importing ToolkitPy itself. A `.env` (or real env
vars) supplies `GAMRY_PYTHON`, `TOOLKITPY_HOME`, and optionally
`GAMRY_SOURCE_ROOT`.

## Usage

```python
from pyproc_bridge import AbortSignal
from potentiostat import ExecuteSequenceConfig, SequenceConfig
from potentiostat.gamry_potentiostat.runner import run_sequence

cfg = ExecuteSequenceConfig(
    technique_keys=["ocp", "eis", "lpr", "cpp"],
    outdir="./run_output",
    config=SequenceConfig(),  # tweak OCP/EIS/LPR/CPP fields for a real run
)

# Any interpreter: spawns the Gamry 32-bit Python, streaming events back.
run = run_sequence(cfg, on_event=print, abort=AbortSignal())
results = run.result()  # blocks, re-raises on failure
print(results)  # per-technique outcomes + saved .DTA/.csv paths
```

Under the Gamry interpreter you can skip the subprocess and call
`potentiostat.execute_sequence_sync(cfg, abort=AbortSignal())` directly.
Deeper demos (custom techniques, live plotting) live in [`examples/`](examples/).

## Layout

`core/` hardware + techniques + sequence · `parsing/` config models and `.DTA`
I/O · `plotting/` live dashboard + PNG writer · `utils/` logging and helpers ·
`gamry_potentiostat/` host-side env resolution + worker spawning.

## Development

```powershell
uv sync --extra dev
uv run --extra dev ruff format .   # formatter
uv run --extra dev ruff check .    # linter (E, F)
```

## License

MIT — see [LICENSE](LICENSE).
