# Quantum Lab Demo Support Package

`quantum-lab-demo` is the installable support package behind
`examples/quantum`. It exists to show how a real lab can keep experiment
builders, virtual providers, reusable analysis steps, and fixture
models next to the notebooks that exercise them.

This package is not a stable domain extension. It is intentionally local demo
code used to validate Scopecat's notebook-first UX.

## What Lives Here

- experiment-system Rabi, simultaneous Rabi, manual and parameter-table background
  Rabi, readout-frequency, multiplexed readout, multiplexed readout calibration,
  single-qubit RB, CZ RB, CZ chevron, spectator-aware CZ, parallel gate-set,
  toy surface-code round, QND repeated measurement, and backend-batch modules
  and template entrypoints;
- a promoted `AnalysisStep` implementation for repeated readout-frequency
  analysis;
- domain calculation and plotting helpers behind that promoted analysis step;
- a unified virtual lab provider;
- support-package unit tests.

## Where Users Customize

| Goal | Start here |
|---|---|
| Change reusable template inputs, default points, selected products, or seed inputs | `src/quantum_lab_demo/experiments/templates.py` |
| Add one-off point scans or run-time point/parameter sweeps | `Workspace.prepare(...).scan(...).preview()/run()` or `Workspace.run(..., sweeps=sc.cartesian(sc.sweep(...), sc.sweep_param(...)))` in notebooks |
| Reuse resource, state, compute, record, or product declarations | focused `src/quantum_lab_demo/experiments/*_modules.py` files |
| Generate point-local pulse programs | `src/quantum_lab_demo/experiments/compute.py`, with in-memory payload types in `src/quantum_lab_demo/experiments/payloads.py` |
| Edit lab wiring with qubit/coupler/line vocabulary | `quantum_wiring()`, `default_quantum_wiring()`, and `quantum_wiring_config_profile()` in `src/quantum_lab_demo/virtual_lab/wiring.py` |
| Inspect related readout cases | `../notebooks/08_readout_family.py` |
| Inspect surface-code-shaped and backend-batch cases | `../notebooks/09_system_scale_cases.py` |
| Inspect route-aware waveform compute | `../notebooks/07_gate_calibration_family.py` |
| Change workspace, config profile, or virtual profile paths | `src/quantum_lab_demo/lab.py` and `src/quantum_lab_demo/fixtures.py` |
| Replace virtual hardware with a real adapter | `src/quantum_lab_demo/virtual_lab/provider.py` |
| Keep domain calculations out of notebooks | `src/quantum_lab_demo/experiments/readout_analysis_calculations.py` |
| Turn notebook analysis into reusable code | `src/quantum_lab_demo/experiments/readout_analysis_steps.py` |
| Validate demo behavior | `tests/unit` and `../tests` |

Runnable user-facing examples live one directory up in `examples/quantum`.
Those examples should stay thin: they open `Workspace` objects, keep reusable
`ExperimentModule` declarations in focused domain files such as
`rabi_modules.py`, `readout_modules.py`, `record_modules.py`, and
`two_qubit_modules.py`; keep reusable `ExperimentTemplate` entrypoints in
`templates.py`; pass template constants directly to notebooks; prepare or run
them with fluent terminal calls such as
`Workspace.prepare(...).input(...).scan(...).preview()/run()` or
`Workspace.run(..., inputs=..., sweeps=..., name=..., tags=...)`, inspect
`Run.data()`, save `Analysis`, try candidate configs, and review candidate run
comparisons.

Keep reusable declarations in module/template source. Scratch workspace
experiments are only for notebook exploration; promote them by editing source
when the shape becomes a reference case.

The Rabi and CZ chevron modules intentionally return generated gate-sequence
and waveform payloads as ordinary in-memory Python objects. The CZ chevron
case combines scan variables with the `qubits` and
`two_qubit_gates` parameter tables inside compute functions, then
renders route-aware numpy waveform bundles for the virtual drive and coupler
stacks. The parallel gate-set and toy surface-code cases keep gate schedules
as ordinary in-memory Python objects while records remain dense arrays over
round, shot, entity, or backend-point axes. The runtime wraps those payloads
for instrument commands and emits compact compute summaries, including
dependency metadata for point columns, parameter tables, route ports, and
upstream compute nodes, without hashing arrays or requiring users to write
temporary waveform files.

The lab uses a small quantum wiring builder instead of requiring users
to hand-author the core routing graph. Users describe qubits, couplers, logical
lines, physical channels, and shared LO groups with `quantum_wiring()`, then
the helper validates those references and compiles that view into core
`Topology` lines/channels/groups plus routing channel bindings. Core stays
domain-neutral, while examples remain editable in terms a lab user would
recognize.

## Future Domain Package Boundary

A future `scopecat-quantum` package should start with foundational building
blocks only: gate records, pulse records, sequence records, target identifiers,
and artifact helpers. It should not absorb this demo package's readout
workflows, virtual fixtures, candidate activation policy, or notebook examples.

## Checks

From the repository root:

```sh
uv run --offline pytest examples/quantum/support/tests
uv run --offline ruff check examples/quantum/support
uv run --offline ruff format --check examples/quantum/support
uv run --offline basedpyright
```
