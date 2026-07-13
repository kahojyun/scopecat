# Scopecat Quantum Examples

Executable quantum-flavored examples for learning the Scopecat workflow:

```text
Module -> Template -> Prepared/Workspace Experiment -> Run -> Data -> Analysis
```

The primary learning path is the cell-style Python notebooks in `notebooks/`.
They are ordinary `# %%` files: run them top to bottom in VS Code or execute
the notebook files directly from the command line. The demo lab code they
import lives in `support/` as the `quantum_lab_demo` package. Treat that
support package as copyable example lab code, not as a stable product API.

## Run The Learning Path

From the repository root:

```sh
uv run python examples/quantum/notebooks/01_open_workspace.py
uv run python examples/quantum/notebooks/02_define_experiment.py
uv run python examples/quantum/notebooks/03_run_and_read_data.py
uv run python examples/quantum/notebooks/04_manual_analysis.py
uv run python examples/quantum/notebooks/05_promote_analysis_step.py
uv run python examples/quantum/notebooks/06_review_candidate_and_rerun.py
uv run python examples/quantum/notebooks/07_gate_calibration_family.py
uv run python examples/quantum/notebooks/08_readout_family.py
uv run python examples/quantum/notebooks/09_system_scale_cases.py
uv run python examples/quantum/notebooks/10_fake_awg_template.py
uv run python examples/quantum/notebooks/11_fake_awg_scratch.py
uv run python examples/quantum/notebooks/12_fake_awg_with_bias.py
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
| `notebooks/02_define_experiment.py` | Set qubit and scan values, then build an experiment. |
| `notebooks/03_run_and_read_data.py` | Run once, keep the run in scope, and inspect `Run.data()`. |
| `notebooks/04_manual_analysis.py` | Build one-off notebook analysis and candidate evidence. |
| `notebooks/05_promote_analysis_step.py` | Replace repeated manual analysis with an `AnalysisStep`. |
| `notebooks/06_review_candidate_and_rerun.py` | Run a candidate config, compare runs, and review the comparison. |
| `notebooks/07_gate_calibration_family.py` | Preview related Rabi and CZ cases as one gate-calibration family, including parameter-table background state, run-time parameter scans, and waveform compute events. |
| `notebooks/08_readout_family.py` | Preview single, multiplexed, calibrated, and QND readout cases as one readout family. |
| `notebooks/09_system_scale_cases.py` | Preview surface-code-shaped and backend-batch cases that exercise larger array and backend semantics. |
| `notebooks/10_fake_awg_template.py` | Run a reusable quantum Template as one fake AWG list plus digitizer acquisition and host IQ discrimination. |
| `notebooks/11_fake_awg_scratch.py` | Define and run the same target path through the scratch `Experiment` authoring style. |
| `notebooks/12_fake_awg_with_bias.py` | Cross a scalar DC-voltage source with the programmable X-count axis and let one unified backend batch the fake AWG work between voltage changes. |

## Adapting The Demo

When copying this example into a lab repository, keep the notebook path small
and move repeated lab details into a local support package:

| User change | Edit here | Keep notebooks using |
|---|---|---|
| Change reusable scan defaults, exposed inputs, or selected products | `support/src/quantum_lab_demo/experiments/templates.py` | template constants plus `Workspace.prepare(...).input(...).scan(...).preview()/run()` |
| Reuse resource, state, compute, record, or product declarations | focused `support/src/quantum_lab_demo/experiments/*_modules.py` files | explicitly named `module.instantiate(...)` values passed to templates or `Workspace.experiment(...).use(...)` |
| Try a one-off scan or product selection | notebook cells with `Workspace.experiment(...)` or `Workspace.prepare(...).scan(...)` | fluent terminal methods: `preview()`, `validate()`, `run()` |
| Change waveform or sequence generation | `support/src/quantum_lab_demo/experiments/compute.py` plus payload types in `support/src/quantum_lab_demo/experiments/payloads.py` | template constants; runtime payload summaries |
| Edit qubit, coupler, channel, line, or shared-LO wiring | `support/src/quantum_lab_demo/virtual_lab/wiring.py` | `quantum_wiring()` compiled into config |
| Change workspace roots, fixture paths, or profile selection | `support/src/quantum_lab_demo/lab.py` and `support/src/quantum_lab_demo/fixtures.py` | `sc.open(...)` |
| Replace virtual hardware with a lab adapter | `support/src/quantum_lab_demo/virtual_lab/provider.py` | `Workspace.prepare(...).input(...).run()` |
| Adapt gate/pulse compilation to a target | `support/src/quantum_lab_demo/reference_experiments/` and `targets/fake_list_mode/` | one `ExecutionBackend` whose provider and domain adapters declare their capabilities |
| Change one-off analysis | `notebooks/04_manual_analysis.py` | `Run.data()` and `Run.analysis(...)` |
| Promote repeated analysis | `support/src/quantum_lab_demo/experiments/readout_analysis_steps.py` | `Run.analyze(...)` |
| Try a candidate config | `notebooks/06_review_candidate_and_rerun.py` | `Analysis.candidate_config()` and `Workspace.prepare(..., config=candidate).input(...).run()` |

The support package may contain domain calculations, virtual fixtures, and
adapter wiring. User-facing notebooks should stay on Scopecat public objects
and top-level notebook variables: `Workspace`, `Experiment`, `Run`, `Data`,
`Analysis`, and `CandidateConfig`. Keep notebooks importing template constants
from `quantum_lab_demo.experiments`; move reference cases into focused module
and template definitions when scratch exploration becomes reusable.

The support package also contains a runnable fake list-mode AWG/acquisition
reference path. Notebooks 10 and 11 demonstrate checked quantum target
compilation, correlated domain submit/fetch/reconcile, producer-neutral host
value assembly, typed `POINT` measurement transformation, record projection,
and receipt-bearing per-point recording. Its binary-IQ fixture keeps raw shots
under domain ownership and derived probabilities under transform ownership.
Both authoring styles use the lab's single `ExecutionBackend` and converge on
the same `Workspace.prepare(...).run()` workflow; the domain adapter is a
capability-owning target boundary, not a second execution mode or experiment
API.

Notebook 12 shows why the backend is unified. A simple point-local voltage
source cannot accept lists, while the fake AWG can compile several X-count
points into one list. The experiment crosses voltage and X count in one logical
scan. With automatic fusion, local voltage changes partition the run into one
AWG invocation per voltage block; `ExecutionOptions(fusion="disabled")` instead
requests one target invocation per logical point. In either case, users receive
the same eight logical measurement records.

The domain runtime remains intentionally synchronous: each submitted batch's
initial fetch must return a terminal result. A pending result is persisted as an
indeterminate contract failure, and an uncertain submit retains target,
artifact, submission-key, and reconciliation evidence in the standard Run, but
there is no automatic resume API yet.

The current notebook virtual provider still synthesizes probability products
directly and remains legacy demo debt for the older examples. The reference
currently records integrated IQ as well as probabilities because the authoring
DSL cannot yet demand a transform input without also projecting it as a record;
that asymmetry is now a visible UX benchmark. `POINT_SET`, cross-point analysis,
transform authoring DSL, hidden intermediate-product demand, offload
equivalence, dataset compaction, polling, and cancellation remain later work.

The examples use domain names such as `qubit`, `control_qubit`, and
`partner_qubit` as run-time `inputs` keys. Linked experiment specs lower
entity references to ordinary point columns or parameter-table rows rather than
storing a special `target` field.

## Checks

```sh
uv run --offline pytest examples/quantum/tests examples/quantum/support/tests
uv run --offline ruff check examples/quantum
uv run --offline ruff format --check examples/quantum
uv run --offline basedpyright
```

The notebook tests execute the `# %%` files directly and assert on the
variables left in the notebook namespace. Keep examples as visible, top-level
notebook cells.
