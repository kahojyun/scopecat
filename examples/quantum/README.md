# Scopecat Quantum Demo

This project has one supported user workflow: calibrate the DRAG beta for `q0`.
It exercises the complete product path without alternate authoring scenarios:

```text
Default config → DRAG run → Analysis → Candidate run → Accept → Production run → Undo
```

## Run the demo

Start the daemon from the repository root:

```sh
cd apps/scopecat-ui
pnpm install --frozen-lockfile
pnpm run build
cd ../..
uv run scopecat start examples/quantum --static-dir apps/scopecat-ui/dist
uv run scopecat open examples/quantum
```

Then execute the single notebook-style entry:

```sh
uv run python examples/quantum/notebooks/calibration/01_drag_beta.py
```

The file can also be run cell by cell in an editor. It:

1. prepares and runs `drag_beta_template()`;
2. runs `run.analyze(drag_beta_analysis())` against the measurement dataset;
3. saves table and figure evidence plus one parameter proposal;
4. runs once with the candidate without changing the default;
5. accepts that candidate through the daemon;
6. runs a production X90 against the accepted default; and
7. undoes the activation while retaining the audit trail.

The daemon selects a loopback port and records it in the project. Notebook code
discovers that shared instance automatically. Set `SCOPECAT_DAEMON_URL` only to
connect to another loopback instance.

The lab also exposes `run_quantum(call)` for a newly authored
`QuantumProgramCall` that exposes the lab's integrated-IQ result `iq_shots`.
The runner injects this lab's compiler inputs, discrimination, and dataset
recording policy, and the returned experiment can be extended with `.scan(...)`
before passing it to `lab.run(...)`. No wrapper module is required. Independent
auxiliary-device work can be added inside the lab runner; hardware that must
change synchronously at every quantum point belongs in the quantum
target/compiler contract.

## Source map

| Path | Responsibility |
|---|---|
| `notebooks/calibration/01_drag_beta.py` | The only user-facing golden workflow. |
| `support/src/quantum_lab_demo/workflows/drag_beta_experiment.py` | DRAG template and scan definition. |
| `support/src/quantum_lab_demo/workflows/drag_beta_analysis.py` | Measurement fitting and candidate proposal. |
| `support/src/quantum_lab_demo/workflows/production_drag_gate.py` | Production use of the accepted parameter. |
| `support/src/quantum_lab_demo/quantum_runner.py` | Lab-owned program placement, compiler inputs, postprocess, and recording policy. |
| `support/src/quantum_lab_demo/application.py` | Planning and bootstrap composition. |
| `support/src/quantum_lab_demo/backend.py` | Worker-only virtual instrument composition. |
| `config/` and `support/src/quantum_lab_demo/parameters.py` | User-owned system and bootstrap parameter sources. |

The support package is copyable demo code, not a stable product API. The daemon
owns immutable config entries, active selection, approvals, and activation
history after bootstrap.

## Checks

```sh
uv run pytest examples/quantum/tests
uv run ruff check examples/quantum
uv run ruff format --check examples/quantum
uv run basedpyright
```
