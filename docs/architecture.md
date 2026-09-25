# Architecture

## Why two interpreters

ToolkitPy only installs into Gamry's bundled **32-bit Python 3.7**. Everything
that talks to hardware must run there; everything else can run on any modern
interpreter.

| Runs under Gamry 3.7 | Runs on any interpreter |
|---|---|
| `potentiostat.core` -- hardware I/O, technique runners, sequence driver | `potentiostat.parsing`, `potentiostat.plotting`, `potentiostat.utils`, `potentiostat.gamry_potentiostat` |

`gamry_potentiostat.runner.run_sequence()` bridges the gap: it spawns the
Gamry Python as an IPC worker (via the external `pyproc-bridge` package) and
streams events back, so the host never imports ToolkitPy.

```
host (any Python)                     worker (Gamry Python 3.7)
  run_sequence(cfg) ──TASK──▶ potentiostat.core.sequence.sequence_script
        ◀──EVENT── ...       └─ execute_sequence_sync(cfg)
        ◀──RESULT/ERROR/ABORTED
```

Events are JSON (`WorkflowEvent`); the worker sends exactly one terminal
message. `gamry_potentiostat/env_validation.py` resolves/validates the
interpreter, Framework folder and `PYTHONPATH` before spawning, and installs
`pydantic<2.6` there if missing.

## Module map

```
core/
  hardware/     connect + shared ToolkitPy setup + device-parameter validation
  techniques/   Technique ABC + registry, and run_ocp/eis/lpr/cpp
  sequence/     execute_sequence[_sync] + the IPC worker entry point
  workflow/     WorkflowEvent types + emitter fan-out
parsing/        pydantic config models, .GSequence parser, .DTA I/O
plotting/       per-technique plotters, live panel, post-run PNG writer
utils/          throttle/progress helpers, technique-key math, console log
gamry_potentiostat/  host-side env resolution + worker spawning
```

## Run lifecycle

1. `ExecuteSequenceConfig` is validated and JSON-dumped to the worker.
2. The worker opens the device (`open_session`), validates the config against
   the connected model, then runs each technique in order.
3. Each `Technique.run` emits `technique_start`, throttled `technique_progress`
   events, then (on success) writes CSV and emits `technique_finish`. A failure
   emits `technique_error`, trips the abort signal and re-raises.
4. The OCP result's final potential (`e_ocp`) is carried into the following
   techniques as their reference.

## Data flow

- Raw curves stay in the worker; only artefact paths cross the IPC hop
  (`TechniqueOutcome`).
- Each technique writes `<outdir>/<key>.dta` (ToolkitPy's own writer) and
  `<outdir>/<key>.csv` on the worker side.
- `SequenceResults` is `{key: TechniqueOutcome}` on the host side.
