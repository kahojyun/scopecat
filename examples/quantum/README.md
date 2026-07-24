# Scopecat Quantum Examples

Executable examples for learning the Scopecat workflow:

```text
Default config -> Experiment -> Run -> Data -> Analysis -> Candidate -> Accept/Undo
```

The `# %%` Python files under `notebooks/` are the user-facing learning path.
Run them top to bottom in an editor or as ordinary Python files. Reusable demo
lab code lives in `support/` as `quantum_lab_demo`; it is copyable example code,
not a stable product API.

Start the project daemon once from the repository root:

```sh
uv run scopecat start examples/quantum
uv run scopecat open examples/quantum
```

The daemon selects an available loopback port and records it in the project.
Notebook code discovers that shared instance; scratch Python remains in the
notebook process while all durable effects pass through the daemon. Set
`SCOPECAT_DAEMON_URL` only to override discovery with another loopback URL.

## Configuration ownership

Keep infrastructure descriptions under `config/` and initial parameter tables
in `quantum_lab_demo.parameters`. The project application parses the typed
system and environment schemas, builds table values with Python, and combines
them into one immutable bootstrap snapshot before crossing the daemon boundary:

```python
import scopecat as sc
from quantum_lab_demo import EXAMPLE_ROOT

project = sc.open_project(EXAMPLE_ROOT)
bootstrap_config = project.load_application().bootstrap_config
assert bootstrap_config is not None
snapshot = bootstrap_config()
```

The source files remain user-owned code and configuration. On first startup the
daemon imports the application snapshot; it then owns the immutable entries,
active selection, activation history, and the exact snapshot accepted by each
run. Restarting the daemon does not reapply the bootstrap profile over a later
operator selection.

System topology, connection resources, and virtual instrument behavior remain
JSON assets because they are not the table-editing workflow demonstrated here.
Scalar and table parameter values are ordinary reviewed Python source.
After changing that source, use `scopecat config diff examples/quantum` and
`scopecat config apply examples/quantum` to compare and publish it explicitly.
The daemon does not hot-reload project code.

Ordinary notebook code expresses intent rather than registry mechanics:

```python
draft = lab.config.edit().replace_scalar("repetitions", sc.Quantity(256, "count"))
changed = lab.config.set_default(draft, note="increase averaging")
accepted = lab.config.accept(analysis, note="fit passed")
restored = lab.config.undo(note="restore the previous default")
```

These calls retain immutable revisions, acceptance decisions, and activation
history. Candidate
configuration can be used for one optional run without changing the default,
or accepted directly from durable analysis evidence. Entry ids, registry
generations, and explicit activation remain available in `advanced/`.

## Learning paths

Start with `getting_started/`, then choose a path by intent:

| Directory | Responsibility |
|---|---|
| `notebooks/getting_started/` | Project, template, run, data, analysis, and candidate-config lifecycle. |
| `notebooks/authoring/` | Recommended decorator and function authoring, from template/scratch through recursive quantum programs. |
| `notebooks/calibration/` | Longer parameter calibration workflows, including policy-based acceptance without mandatory verification. |
| `notebooks/integration/` | The opaque collection escape hatch for a target without a domain compiler. |
| `notebooks/advanced/` | Explicit registry, review, activation generation, and rollback controls. |

For example:

```sh
uv run python examples/quantum/notebooks/getting_started/01_open_project.py
uv run python examples/quantum/notebooks/getting_started/02_edit_config.py
uv run python examples/quantum/notebooks/authoring/01_template_and_scratch.py
uv run python examples/quantum/notebooks/authoring/03_point_bound_sequence.py
uv run python examples/quantum/notebooks/calibration/01_drag_beta.py
uv run python examples/quantum/notebooks/advanced/01_config_registry_controls.py
```

## Notebook map

| File | What it teaches |
|---|---|
| `getting_started/01_open_project.py` | Open the demo project and connect its daemon client. |
| `getting_started/02_edit_config.py` | Preview typed scalar and keyed-table edits, set the result as default, then undo. |
| `getting_started/03_define_experiment.py` | Compose a reusable module into a template with a configurable scan. |
| `getting_started/04_run_and_read_data.py` | Run an experiment and inspect `Run.data()`. |
| `getting_started/05_manual_analysis.py` | Save one-off notebook analysis and candidate evidence. |
| `getting_started/06_promote_analysis_step.py` | Promote repeated analysis with `@sc.analysis_step`. |
| `getting_started/07_rerun_candidate_config.py` | Optionally run a durable candidate, accept it as default, and undo. |
| `authoring/01_template_and_scratch.py` | Compare reusable `@sc.template` and caller-configured `@sc.scratch`. |
| `authoring/02_instrument_composition.py` | Compose a scalar instrument with a programmable quantum scan. |
| `authoring/03_point_bound_sequence.py` | Generate a composable `@q.fragment` after length and seed bind per scan point. |
| `authoring/04_recursive_results.py` | Derive dense result axes from nested `parallel` and `repeat`. |
| `authoring/05_mixed_gate_pulse.py` | Place standard-gate preparation and analysis around a direct multi-channel pulse layout. |
| `calibration/01_drag_beta.py` | Accept a high-confidence fit with a versioned automatic policy, then undo. |
| `calibration/02_cz_phase.py` | Calibrate a two-qubit gate with an explicit coupler resource. |
| `integration/01_opaque_collection.py` | Preserve one gate table as one opaque compute input when no domain compiler exists. |
| `advanced/01_config_registry_controls.py` | Register, activate, and roll back with explicit entry ids and generations. |
| `advanced/02_manual_candidate_review.py` | Review and activate an analysis proposal with explicit operator controls. |

## Support package responsibilities

The support package separates code by why it exists:

| Package | Responsibility |
|---|---|
| `quantum_lab_demo.workflows` | Recommended, user-copyable vertical workflows. Import a specific workflow module rather than a package-wide barrel. |
| `quantum_lab_demo.scenarios` | Integration boundaries that intentionally depart from normal domain authoring. |
| `quantum_lab_demo.application` | Version-controlled daemon composition loaded from `scopecat.toml`. |
| `scopecat.open_project` | Core notebook client discovery and delegated execution against the shared daemon. |
| `scopecat_quantum.standard_gates` | Opt-in conventional hardware-independent gate semantics. |
| `quantum_lab_demo.virtual_lab.compiler_parameters` | Materialize typed point-effective compiler values from parameter collections. |
| `quantum_lab_demo.virtual_lab.pulse_profile` | Declare compiler-owned recipes and map them over those values. |
| `quantum_lab_demo.virtual_lab.responses` | Deterministic response generation used by the fake laboratory. |
| `quantum_lab_demo.targets` | Target compiler/runtime adapters. |

Tests have a separate job. Notebook tests only execute every learning-path file
as documentation smoke tests against one real HTTP daemon. Exact artifact,
provenance, shape, response, and configuration assertions live in
`support/tests/`, so notebooks remain readable.

## Capability matrix

A quantum program call represents one experiment point. Length, seed, pulse
parameters, and other varying values remain ordinary scan axes. Within that
point, `q.sequence`, `q.parallel`, and `q.repeat` form one recursive program;
result axes follow the same tree.

The demo calls `with_compiler_inputs(qubits=...)` separately from those
program arguments. Its complete typed `qubits` table comes from the accepted
snapshot plus point overlays, so control and readout fields can be scanned without
becoming Program ports or mutable compiler state.

The lab adapter materializes that collection into a typed point snapshot. A
static `PulseRecipeProfile` joins the bound program's actual gate and
measurement operations to matching rows; the compiler only invokes its generic
materializer. Pulse provenance records both the stable recipe ID and the
resolved template fingerprint; parameter tables never contain `PulseProgram`
objects.

| Scale or boundary | Required capability | Minimal coverage |
|---|---|---|
| Scalar instrument workflow | Module, template, scan, analysis, optional candidate run, accept, and undo | `getting_started/03`–`07` |
| Reusable versus one-off definition | `@sc.template` and `@sc.scratch` over the same semantics | `authoring/01_template_and_scratch.py` |
| One qubit, generated sequence | Point-bound Python elaboration with length and seed scans | `authoring/03_point_bound_sequence.py` and `workflows/single_qubit_rb.py` |
| Repeated multi-qubit acquisition | Recursive repeat and parallel result axes | `authoring/04_recursive_results.py` |
| Realtime feedback | Retained loops, measurement branches, symbolic result layouts, and a statically claimed target | `workflows/active_reset.py` and `support/tests/unit/test_fake_realtime_domain_e2e.py` |
| Low-level interaction characterization | Standard-gate preparation and basis rotation around a direct, offset multi-channel pulse layout; the same source program targets list and realtime hardware | `authoring/05_mixed_gate_pulse.py`, `workflows/interaction_tomography.py`, `support/tests/unit/test_interaction_tomography.py`, and `support/tests/unit/test_fake_realtime_domain_e2e.py` |
| Pulse candidate | Explicit candidate pulses plus policy-based parameter acceptance | `calibration/01_drag_beta.py` |
| Two-qubit calibration | Gate semantics plus an explicit coupler resource | `calibration/02_cz_phase.py` |
| No domain compiler | Preserve one collection as one opaque compute input | `integration/01_opaque_collection.py` |
| Registry troubleshooting | Explicit registration, CAS activation, manual review, and rollback | `advanced/` |

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
