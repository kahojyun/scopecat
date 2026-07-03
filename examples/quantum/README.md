# Scopecat Quantum Examples

Executable quantum-flavored examples for learning the Scopecat workflow:

```text
Workspace -> Experiment -> Run -> Data -> Analysis -> CandidateConfig
```

The primary learning path is the cell-style Python notebooks in `notebooks/`.
They are ordinary `# %%` files: run them top to bottom in VS Code or execute
them as scripts from the command line. The demo lab code they import lives in
`support/` as the `quantum_lab_demo` package. Treat that support package as
copyable example lab code, not as a stable product API.

## Run The Learning Path

From the repository root:

```sh
uv run python examples/quantum/notebooks/01_open_workspace.py
uv run python examples/quantum/notebooks/02_define_experiment.py
uv run python examples/quantum/notebooks/03_run_and_read_data.py
uv run python examples/quantum/notebooks/04_manual_analysis.py
uv run python examples/quantum/notebooks/05_promote_analysis_step.py
uv run python examples/quantum/notebooks/06_review_candidate_and_rerun.py
```

For VS Code notebook/cell execution, sync the workspace environment first.
The default sync includes the notebook kernel dependencies:

```sh
uv sync
```

## Notebook Map

| File | What it teaches |
|---|---|
| `notebooks/01_open_workspace.py` | Open the demo lab and inspect the workspace handle. |
| `notebooks/02_define_experiment.py` | Set qubit and sweep values, then build an experiment. |
| `notebooks/03_run_and_read_data.py` | Run once, keep the run in scope, and inspect `Run.data()`. |
| `notebooks/04_manual_analysis.py` | Build one-off notebook analysis and candidate evidence. |
| `notebooks/05_promote_analysis_step.py` | Replace repeated manual analysis with an `AnalysisStep`. |
| `notebooks/06_review_candidate_and_rerun.py` | Run a candidate config, compare runs, and review the comparison. |

## Script Wrappers

The `scripts/` directory contains thin command-line wrappers around the same
demo lab workflows:

```sh
uv run python examples/quantum/scripts/preview.py
uv run python examples/quantum/scripts/readout_frequency.py
uv run python examples/quantum/scripts/readout_iq.py
uv run python examples/quantum/scripts/sample_experiments.py
```

## Adapting The Demo

When copying this example into a lab repository, keep the notebook path small
and move repeated lab details into a local support package:

| User change | Edit here | Keep notebooks using |
|---|---|---|
| Change qubit, sweep span, points, or experiment defaults | `support/src/quantum_lab_demo/readout/templates.py` or `support/src/quantum_lab_demo/sample/templates.py` | `Workspace.experiment(...)` |
| Change workspace roots, fixture paths, or profile selection | `support/src/quantum_lab_demo/lab.py` and `support/src/quantum_lab_demo/fixtures.py` | `sc.open(...)` |
| Replace virtual hardware with a lab adapter | `support/src/quantum_lab_demo/virtual_lab/provider.py` | `Workspace.run(...)` |
| Change one-off analysis | `notebooks/04_manual_analysis.py` | `Run.data()` and `Run.analysis(...)` |
| Promote repeated analysis | `support/src/quantum_lab_demo/readout/analysis_steps.py` | `Run.analyze(...)` |
| Try a candidate config | `notebooks/06_review_candidate_and_rerun.py` | `Analysis.candidate_config()` and `Workspace.run(..., config=candidate)` |

The support package may contain domain calculations, virtual fixtures, and
adapter wiring. User-facing notebooks should stay on Scopecat public objects
and top-level notebook variables: `Workspace`, `Experiment`, `Run`, `Data`,
`Analysis`, and `CandidateConfig`.

The examples use domain names such as `qubit`, `control_qubit`, and
`partner_qubit` as ergonomic template arguments. Durable experiment plans lower
subjects to ordinary point columns or parameter-table rows rather than storing
a special `target` field.

## Checks

```sh
uv run --offline pytest examples/quantum/tests examples/quantum/support/tests
uv run --offline ruff check examples/quantum
uv run --offline ruff format --check examples/quantum
uv run --offline basedpyright
```

The notebook tests execute the `# %%` files directly and assert on the
variables left in the notebook namespace. Keep reusable command wrappers in
`scripts/`; keep notebooks as visible, top-level cells.
