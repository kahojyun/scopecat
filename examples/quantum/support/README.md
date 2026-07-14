# Quantum Lab Demo Support Package

`quantum-lab-demo` is the installable support package behind
`examples/quantum`. It shows how a lab can keep reusable experiment builders,
virtual providers, analysis steps, target adapters, and fixtures next to thin
notebooks.

This is copyable local example code, not a stable product API. Runnable
user-facing examples live one directory up.

## Where To Make Changes

| Goal | Start here |
|---|---|
| Change reusable inputs, scan defaults, or selected products | `src/quantum_lab_demo/experiments/templates.py` |
| Reuse resource, state, compute, or product declarations | `src/quantum_lab_demo/experiments/*_modules.py` |
| Generate point-local programs | `src/quantum_lab_demo/experiments/compute.py` and `payloads.py` |
| Edit qubit, coupler, line, channel, or shared-LO wiring | `src/quantum_lab_demo/virtual_lab/wiring.py` |
| Change workspace, fixture, or profile paths | `src/quantum_lab_demo/lab.py` and `fixtures.py` |
| Replace virtual instruments with a lab provider | `src/quantum_lab_demo/virtual_lab/provider.py` |
| Adapt circuit and pulse compilation to a target | `src/quantum_lab_demo/targets/fake_list_mode/` |
| Inspect reusable target preparation | `src/quantum_lab_demo/reference_experiments/` |
| Keep analysis calculations out of notebooks | `src/quantum_lab_demo/experiments/readout_analysis_calculations.py` |
| Promote repeated analysis | `src/quantum_lab_demo/experiments/readout_analysis_steps.py` |
| Validate the support package | `tests/unit` and `../tests` |

Keep shared declarations in modules and templates; use
`Workspace.experiment(...)` for one-off composition. Notebook code should stay
on public Scopecat workflow objects and import focused definitions from this
package. Laboratory adapters should use `scopecat.sdk` and
`scopecat-quantum`, not compiler internals. The precise target, correlation,
and runtime invariants are documented in the modules that implement them.

## Checks

From the repository root:

```sh
uv run --offline pytest examples/quantum/support/tests
uv run --offline ruff check examples/quantum/support
uv run --offline ruff format --check examples/quantum/support
uv run --offline basedpyright
```
