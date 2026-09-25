# Techniques

## Built-in

| Key | Technique | What it does | DTA tag |
|---|---|---|---|
| `ocp` | Open-Circuit Potential | logs Eoc vs time at rest | `CORPOT` |
| `eis` | Electrochemical Impedance Spectroscopy | log-spaced AC frequency sweep | `EISPOT` |
| `lpr` | Polarization Resistance | narrow mV ramp around Eoc | `POLRES` |
| `cpp` | Cyclic Polarization | wide anodic sweep to breakdown, then back | `CYCPOL` |

A sequence must start with `ocp`; keys must be unique. Order otherwise is free.

## Config

Each technique owns a `GamryBaseConfig` subclass on `SequenceConfig`
(`ocp`, `eis`, `lpr`, `cpp`). Field names mirror the `.GSequence` wizard,
with the original tags as aliases (e.g. `OCPConfig.total_time_s` is
`TIMEOUT`), so a parsed sequence file fills the same models.

```python
from potentiostat import SequenceConfig

cfg = SequenceConfig()
cfg.eis.initial_freq_hz = 10000
cfg.cpp.v_apex_v = 1.2
cfg.save("sequence.json")  # SequenceConfig.load(path) reads it back
```

Potentials flagged `*_versus_eoc` are resolved against the OCP reading at run
time; otherwise they are absolute.

## Adding a technique

1. Subclass `Technique[YourConfig]` and set `name` -- `__init_subclass__`
   auto-registers it.
2. Implement `_initialize` (control mode) and `_measure` (configure the
   signal, acquire the curve, write the `.DTA`; return `(TechniqueResult, new_e_ocp)`).
3. Set `col_mapping` for the CSV columns, and optionally `plotter`.
4. To use it through `execute_sequence`, add its config to a `SequenceConfig`
   subclass under the same name -- the driver looks it up with
   `getattr(config, technique_name)`.

`TechniqueResult` is a `TypedDict` with `data`, `dta_path`, `csv_path`
(and optional `legs` for multi-leg scans). Progress is reported through
`ctx.emitter.emit_progress(...)`.

See `examples/` for a minimal one-technique run, a custom technique, and
custom control flow.
