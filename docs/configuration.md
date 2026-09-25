# Configuration

## Environment (`.env`)

Copy [`.env.example`](../.env.example) to `.env` (gitignored). All values are
optional; a real environment variable overrides `.env`.

| Variable | Purpose | Default |
|---|---|---|
| `GAMRY_PYTHON` | Gamry-provided 32-bit Python 3.7 with ToolkitPy | auto-detected from the standard install path |
| `TOOLKITPY_HOME` | Gamry `Framework` folder, if ToolkitPy is installed with `--target` there | auto-detected next to `GAMRY_PYTHON` |
| `GAMRY_SOURCE_ROOT` | Directory **containing** the `potentiostat` package, for dev runs | auto-detected from the checkout |

`pydantic<2.6` and `pyproc-bridge` are handled automatically by
`gamry_potentiostat/env_validation.py`.

## Sequence configuration

`ExecuteSequenceConfig` is what you pass to a run:

| Field | Meaning |
|---|---|
| `technique_keys` | Ordered keys, e.g. `["ocp", "eis", "lpr", "cpp"]`; must start with `ocp`, no duplicates |
| `outdir` | Directory for `.dta` / `.csv` outputs (`<key>.dta`, `<key>.csv`) |
| `config` | `SequenceConfig` with the per-technique parameters |
| `pstat_name` | Optional potentiostat section name; first found if `None` |

`SequenceConfig.save(path)` writes JSON; `SequenceConfig.load(path)` reads JSON
or a Gamry `.GSequence` XML file (an empty/missing path returns defaults).
Per-potentiostat limits are checked against the connected model's specs, or the
`GENERIC` fallback.

## Outputs

- `<outdir>/<key>.dta` -- written by ToolkitPy during the measurement.
- `<outdir>/<key>.csv` -- tidy columns from the technique's `col_mapping`.
- PNGs via `potentiostat.plotting.save_plots` / `save_combined_plots`.
