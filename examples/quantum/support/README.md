# Quantum Lab Demo Support Package

`quantum-lab-demo` is the local support package used by the runnable examples
in `examples/quantum`. It contains reusable experiment definitions, analysis,
virtual laboratory configuration, and one quantum lab compiler so the
notebooks can focus on the user workflow.

This is copyable example code, not a stable product API or a required layout
for laboratory projects.

## Package Map

Inside `src/quantum_lab_demo/`:

- `workflows/`: recommended vertical `@q.program`, module, template, scratch,
  analysis, and production examples.
- `scenarios/`: the opaque collection boundary for a target without a domain
  compiler.
- `lab.py`: the composition root for the configured demo environment.
- `compiler.py`: the unified `QuantumLabCompiler` domain boundary.
- `response_registry.py` and `trace.py`: fake-response selection and observable
  preparation evidence kept outside compiler policy.
- `targets/`: fake target lowering and execution.
- `virtual_lab/`: wiring, typed parameter collections, instrument providers,
  point-effective calibration lowering, and fake responses.

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
