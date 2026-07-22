# Scopecat Quantum Examples

Executable quantum-flavored examples for learning the Scopecat workflow:

```text
Quantum Program -> Module -> Template/Scratch -> Prepared Experiment -> Run -> Data
```

The primary learning path is the cell-style Python notebooks in `notebooks/`.
They are ordinary `# %%` files: run them top to bottom in VS Code or execute
the notebook files directly from the command line. The demo lab code they
import lives in `support/` as the `quantum_lab_demo` package. Treat that
support package as copyable example lab code, not as a stable product API.

The demo `ExperimentSystem` shares one `QuantumLabCompiler` across every
quantum program; notebooks 13 and 15 show calibration through the ordinary
parameter proposal, review, and activation workflow.

## Run The Core Learning Path

From the repository root:

```sh
uv run python examples/quantum/notebooks/01_open_workspace.py
uv run python examples/quantum/notebooks/02_define_experiment.py
uv run python examples/quantum/notebooks/03_run_and_read_data.py
uv run python examples/quantum/notebooks/04_manual_analysis.py
uv run python examples/quantum/notebooks/05_promote_analysis_step.py
uv run python examples/quantum/notebooks/06_rerun_candidate_config.py
uv run python examples/quantum/notebooks/10_fake_awg_template.py
uv run python examples/quantum/notebooks/11_fake_awg_scratch.py
uv run python examples/quantum/notebooks/12_fake_awg_with_bias.py
uv run python examples/quantum/notebooks/14_ramsey_phase_dsl.py
uv run python examples/quantum/notebooks/15_cz_conditional_phase.py
```

Notebook 13 is the longer calibration lifecycle reference. Notebooks 07–09
are coverage galleries for experiment families and backend shapes; they are
useful when extending the demo, but are not prerequisites for authoring a
normal experiment.

For VS Code notebook/cell execution, sync the workspace environment first.
The default sync includes the notebook kernel dependencies:

```sh
uv sync
```

## Notebook Map

| File | What it teaches |
|---|---|
| `notebooks/01_open_workspace.py` | Open the demo lab and inspect the workspace handle. |
| `notebooks/02_define_experiment.py` | Define a reusable template from a module with a Python decorator. |
| `notebooks/03_run_and_read_data.py` | Run once, keep the run in scope, and inspect `Run.data()`. |
| `notebooks/04_manual_analysis.py` | Build one-off notebook analysis and candidate evidence. |
| `notebooks/05_promote_analysis_step.py` | Replace repeated manual analysis with an `AnalysisStep`. |
| `notebooks/06_rerun_candidate_config.py` | Run a follow-up experiment with a candidate config. |
| `notebooks/07_gate_calibration_family.py` | Coverage gallery for related gate-calibration shapes. |
| `notebooks/08_readout_family.py` | Coverage gallery for single, multiplexed, calibrated, and QND readout. |
| `notebooks/09_system_scale_cases.py` | Coverage gallery for larger point domains and backend batches. |
| `notebooks/10_fake_awg_template.py` | Run a reusable template against the fake AWG and digitizer target. |
| `notebooks/11_fake_awg_scratch.py` | Run the same target through scratch experiment authoring. |
| `notebooks/12_fake_awg_with_bias.py` | Combine a scalar bias source with a programmable quantum scan. |
| `notebooks/13_drag_beta_calibration.py` | Scan an accepted gate parameter, then fit, review, activate, and roll it back. |
| `notebooks/14_ramsey_phase_dsl.py` | Compose a Ramsey sequence from gates, pulses, frames, and acquisition. |
| `notebooks/15_cz_conditional_phase.py` | Calibrate a physical CZ and produce a reviewable parameter proposal. |

## Adapting The Demo

When copying this example into a lab repository, use the pieces that match the
workflow you are building:

| Goal | Start here |
|---|---|
| Learn reusable experiment definitions | `reference_experiments/fake_x_count_experiment.py` |
| Browse broader shape coverage | `support/src/quantum_lab_demo/experiments/` |
| Try one-off scans and product selection | `@sc.scratch` and `Workspace.prepare(...)` |
| Generate a point-dependent gate sequence | `reference_experiments/single_qubit_rb.py` uses `@q.fragment`; Clifford length and seed remain ordinary scan axes. |
| Change laboratory policy, parameters, calibration, or wiring | `support/src/quantum_lab_demo/virtual_lab/` |
| Compose the lab or adapt quantum programs to a target | `support/src/quantum_lab_demo/lab.py`, `compiler.py`, and `targets/` |
| Pass a collection without a domain compiler | The `parallel_gate_collection` cell in notebook 07 passes one tuple of rows into `PARALLEL_GATE_SET_MODULE`; the module keeps that `TableType` value intact through `sc.compute` and opaque payload rendering. |
| Develop analysis and configuration proposals | notebooks 04–06 and the reusable analysis code under `support/` |

The support package is one copyable way to organize repeated lab code, not a
required project structure. The notebooks demonstrate the public workflow
objects: `Workspace`, `ExperimentTemplate`, `ExperimentInvocation`, `Run`,
`Data`, `Analysis`, and `CandidateConfig`.

## Checks

```sh
uv run --offline pytest examples/quantum/tests examples/quantum/support/tests
uv run --offline ruff check examples/quantum
uv run --offline ruff format --check examples/quantum
uv run --offline basedpyright
```

The checks execute the notebook files end to end as ordinary Python programs.
