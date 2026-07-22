# Scopecat Quantum Examples

Executable examples for learning the Scopecat workflow:

```text
Quantum Program -> Module -> Template/Scratch -> Prepared Experiment -> Run -> Data
```

The `# %%` Python files under `notebooks/` are the user-facing learning path.
Run them top to bottom in an editor or as ordinary Python files. Reusable demo
lab code lives in `support/` as `quantum_lab_demo`; it is copyable example code,
not a stable product API.

## Learning paths

Start with `getting_started/`, then choose a path by intent:

| Directory | Responsibility |
|---|---|
| `notebooks/getting_started/` | Workspace, template, run, data, analysis, and candidate-config lifecycle. |
| `notebooks/authoring/` | Recommended decorator and function authoring, from template/scratch through recursive quantum programs. |
| `notebooks/calibration/` | Longer end-to-end parameter calibration and review workflows. |
| `notebooks/integration/` | The opaque collection escape hatch for a target without a domain compiler. |

For example:

```sh
uv run python examples/quantum/notebooks/getting_started/01_open_workspace.py
uv run python examples/quantum/notebooks/authoring/01_template_and_scratch.py
uv run python examples/quantum/notebooks/authoring/03_point_bound_sequence.py
uv run python examples/quantum/notebooks/calibration/01_drag_beta.py
```

## Notebook map

| File | What it teaches |
|---|---|
| `getting_started/01_open_workspace.py` | Open the demo lab and inspect the workspace. |
| `getting_started/02_define_experiment.py` | Compose a reusable module into a template with a configurable scan. |
| `getting_started/03_run_and_read_data.py` | Run an experiment and inspect `Run.data()`. |
| `getting_started/04_manual_analysis.py` | Save one-off notebook analysis and candidate evidence. |
| `getting_started/05_promote_analysis_step.py` | Promote repeated analysis with `@sc.analysis_step`. |
| `getting_started/06_rerun_candidate_config.py` | Run a follow-up experiment with a candidate config. |
| `authoring/01_template_and_scratch.py` | Compare reusable `@sc.template` and caller-configured `@sc.scratch`. |
| `authoring/02_instrument_composition.py` | Compose a scalar instrument with a programmable quantum scan. |
| `authoring/03_point_bound_sequence.py` | Generate a composable `@q.fragment` after length and seed bind per scan point. |
| `authoring/04_recursive_results.py` | Derive dense result axes from nested `parallel` and `repeat`. |
| `authoring/05_mixed_gate_pulse.py` | Mix gates, pulse templates, frames, and acquisition in one program. |
| `calibration/01_drag_beta.py` | Fit, review, activate, and roll back a one-qubit gate parameter. |
| `calibration/02_cz_phase.py` | Calibrate a two-qubit gate with an explicit coupler resource. |
| `integration/01_opaque_collection.py` | Preserve one gate table as one opaque compute input when no domain compiler exists. |

## Support package responsibilities

The support package separates code by why it exists:

| Package | Responsibility |
|---|---|
| `quantum_lab_demo.workflows` | Recommended, user-copyable vertical workflows. Import a specific workflow module rather than a package-wide barrel. |
| `quantum_lab_demo.scenarios` | Integration boundaries that intentionally depart from normal domain authoring. |
| `quantum_lab_demo.virtual_lab.calibrations` | Calibration catalog installed by the fake laboratory. |
| `quantum_lab_demo.virtual_lab.responses` | Deterministic response generation used by the fake laboratory. |
| `quantum_lab_demo.targets` | Target compiler/runtime adapters. |

Tests have a separate job. Notebook tests only execute every learning-path file
as documentation smoke tests. Exact artifact, provenance, shape, response, and
configuration assertions live in `support/tests/`, so notebooks remain readable.

## Capability matrix

A quantum program call represents one experiment point. Length, seed, pulse
parameters, and other varying values remain ordinary scan axes. Within that
point, `q.sequence`, `q.parallel`, and `q.repeat` form one recursive program;
result axes follow the same tree.

| Scale or boundary | Required capability | Minimal coverage |
|---|---|---|
| Scalar instrument workflow | Module, template, scan, analysis, candidate config | `getting_started/02`–`06` |
| Reusable versus one-off definition | `@sc.template` and `@sc.scratch` over the same semantics | `authoring/01_template_and_scratch.py` |
| One qubit, generated sequence | Point-bound Python elaboration with length and seed scans | `authoring/03_point_bound_sequence.py` and `workflows/single_qubit_rb.py` |
| Repeated multi-qubit acquisition | Recursive repeat and parallel result axes | `authoring/04_recursive_results.py` |
| Pulse candidate | Mixed gates, pulses, frames, and accepted calibration | `authoring/05_mixed_gate_pulse.py` and `calibration/01_drag_beta.py` |
| Two-qubit calibration | Gate semantics plus an explicit coupler resource | `calibration/02_cz_phase.py` |
| No domain compiler | Preserve one collection as one opaque compute input | `integration/01_opaque_collection.py` |

A program or circuit collection is not part of the normal model: static
elements compose recursively, while experiment variation belongs to scan axes.
The opaque collection notebook exists only for a target without a domain
compiler. Raw-trace dtype and shape propagation similarly stay focused contract
tests rather than another user-facing experiment.

## Checks

```sh
uv run --offline pytest examples/quantum/tests examples/quantum/support/tests
uv run --offline ruff check examples/quantum
uv run --offline ruff format --check examples/quantum
uv run --offline basedpyright
```
