# Quantum Lab Demo Support Package

`quantum-lab-demo` is the local support package used by the runnable examples
in `examples/quantum`. It contains reusable experiment definitions, analysis,
virtual laboratory configuration, and target adapters so the notebooks can
focus on the user workflow.

This is copyable example code, not a stable product API or a required layout
for laboratory projects.

## Package Map

Inside `src/quantum_lab_demo/`:

- `experiments/`: reusable experiment shapes and analysis steps.
- `reference_experiments/`: complete calibration and production examples.
- `targets/`: fake target compilation and execution.
- `virtual_lab/`: demo wiring and instrument providers.

Focused behavior checks live in `tests/unit/`.

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
