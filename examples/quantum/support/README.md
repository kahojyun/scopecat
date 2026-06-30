# Quantum Lab Demo Support Package

`quantum-lab-demo` is the installable support package behind
`examples/quantum`. It exists to show how a real lab can keep experiment
builders, virtual or native providers, reusable analysis steps, and fixture
models next to the notebooks that exercise them.

This package is not a stable domain extension. It is intentionally local demo
code used to validate Scopecat's notebook-first UX.

## What Lives Here

- readout-frequency and readout-IQ experiment builders;
- sample-backed Rabi, readout, single-qubit RB, and CZ RB builders;
- promoted `AnalysisStep` implementations for repeated readout analysis;
- domain calculation, plotting, and update-loop helpers behind those promoted
  analysis steps;
- virtual lab providers and response models;
- support-package unit tests.

## Where Users Customize

| Goal | Start here |
|---|---|
| Change qubit, sweep, lengths, or seed inputs | `src/quantum_lab_demo/readout/templates.py` and `src/quantum_lab_demo/sample/templates.py` |
| Change workspace, config profile, or virtual profile paths | `src/quantum_lab_demo/lab.py` and `src/quantum_lab_demo/fixtures.py` |
| Replace virtual hardware with a real adapter | `src/quantum_lab_demo/virtual_lab/provider.py` |
| Keep domain calculations out of notebooks | `src/quantum_lab_demo/readout/analysis_calculations.py` |
| Turn notebook analysis into reusable code | `src/quantum_lab_demo/readout/analysis_steps.py` |
| Validate demo behavior | `tests/unit` and `../tests` |

Runnable user-facing examples live one directory up in `examples/quantum`.
Those examples should stay thin: they open `Workspace` objects, define or import
experiments, run them, inspect `Run.data()`, save `Analysis`, and review
candidate configs.

## Future Domain Package Boundary

A future `scopecat-quantum` package should start with foundational building
blocks only: gate records, pulse records, sequence records, target identifiers,
and artifact helpers. It should not absorb this demo package's readout
workflows, virtual fixtures, candidate review policy, or notebook examples.

## Checks

From the repository root:

```sh
uv run --offline pytest examples/quantum/support/tests
uv run --offline ruff check examples/quantum/support
uv run --offline ruff format --check examples/quantum/support
uv run --offline basedpyright
```
