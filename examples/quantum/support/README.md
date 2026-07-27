# Quantum Lab Demo Support Package

`quantum-lab-demo` supports the runnable DRAG-beta example in
`examples/quantum`. It keeps one complete calibration path—from experiment
through analysis, proposal, acceptance, and production use—rather than a
catalog of unrelated scenarios.

This is copyable example code, not a stable product API or a required layout
for laboratory projects.

## Package Map

Inside `src/quantum_lab_demo/`:

- `workflows/`: the DRAG-beta program, experiment, quadratic analysis, and
  production-gate follow-up.
- `application.py`: the daemon-side `LabApplication` composition root.
- `lab.py`: shared configuration, compiler, and experiment-system wiring.
- `configuration.py`: combine schema-checked infrastructure with Python values.
- `parameters.py`: the q0 DRAG calibration row.
- `compiler.py`: the unified `QuantumLabCompiler` domain boundary.
- `targets/`: fake target lowering and execution.
- `virtual_lab/`: q0 drive/readout wiring, compiler parameters, X90/Xm90 pulse
  recipes, and the deterministic DRAG response.

Focused behavior checks live in `tests/unit/`.

Notebook code uses the core `sc.open_project(...).connect()` client. This
support package owns only the demo's user code and application composition, not
a second client facade.

The parent [quantum examples README](../README.md) describes the notebook
learning path and where to start when adapting the demo.

## Checks

From the repository root:

```sh
uv run --offline pytest examples/quantum/support/tests
uv run --offline ruff check examples/quantum/support
uv run --offline ruff format --check examples/quantum/support
uv run --offline basedpyright
```
