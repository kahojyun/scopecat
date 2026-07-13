# Scopecat

<p align="center"><img src="assets/branding/app-icon.svg" alt="Scopecat app icon" width="160"></p>

Scopecat is a local-first Python workspace for describing experiments, running
previews or executing them through instrument providers, and keeping the
resulting runs, data, analysis records, candidate configs, comparisons, and
operator attachments and artifacts together in a workspace.

The core package stays domain-neutral. Example support packages live under
`examples/` when they are only teaching and UX validation code. A real domain
extension should move under `packages/` only after its boundary is worth
freezing.

## Workspace Layout

- `packages/scopecat`: core workspace, experiment, run, data, analysis,
  workflow, storage, run overview, and SDK primitives.
- `packages/scopecat-quantum`: hardware-independent gate, circuit, pulse,
  schedule, calibration-selection, and target-compiler building blocks.
- `examples/quantum`: notebook-first quantum examples, thin script wrappers,
  and the local `quantum_lab_demo` support package.
- `fixtures`: durable sample inputs for core tests, boundary contracts, and
  runnable examples.
- `docs`: design notes and deeper project context.

## Basic Shape

Users normally work through the stable public workflow nouns:

```python
import scopecat as sc

lab = sc.open(
    ".scopecat",
    config="active",
    execution_backend=sc.PointInstrumentBackend(provider),
)
readout_frequency = sc.point(
    "readout_frequency",
    sc.ScalarType(sc.QuantityType()),
)

plan = (
    lab.prepare(readout_frequency_template)
    .input("qubit", "q0")
    .scan(
        readout_frequency,
        span=sc.Quantity(value=100.0, unit="MHz"),
        points=21,
    )
)
preview = plan.preview()
run = plan.run(name="readout frequency")
raw = run.data().measurements()
run.attach(
    key="notebook",
    text="manual scan notes",
    filename="manual-scan-notes.md",
)

analysis = (
    run.analysis("manual readout review", key="readout-review")
    .input("raw-measurements", expected_kind="measurement_dataset")
    .input("notebook", role="notes", expected_kind="attachment")
    .propose(
        "readout_frequency",
        sc.update_parameter_rows(
            "qubits",
            key={"qubit": "q0"},
            values={
                "readout_frequency": sc.Quantity(value=5.5, unit="GHz")
            },
        ),
        reason="lowest S21 point in the readout scan",
    )
)
analysis.save()

candidate = analysis.candidate_config()
next_run = (
    lab.prepare(readout_frequency_template, config=candidate)
    .input("qubit", "q0")
    .scan(
        readout_frequency,
        span=sc.Quantity(value=100.0, unit="MHz"),
        points=21,
    )
    .run(name="readout frequency candidate")
)
comparison = lab.compare(run, next_run)
overview = lab.overview(run)
```

Reusable experiments are usually authored as modules plus templates; scratch
notebook work can use `Workspace.experiment(...)`. The first post-run user path
is `Run.data()`, `Run.attach(...)`, and `Run.analysis(...)`. Attachments belong
directly to the run. Analysis records use stable keys, declare their inputs,
and can be produced manually or through an `AnalysisStep` without changing the
saved record shape.

## Typed Module Wiring

Module inputs, point-local values, and compute outputs are first-class typed
values. Declare them once, then pass the resulting handles through the module
graph and scan DSL; Scopecat keeps their complete value types available when it
validates wiring and scan literals.

```python
import scopecat as sc


def build_program(*, qubits, frequency):
    return {
        "entity_ids": [qubit.id for qubit in qubits],
        "frequency": frequency,
    }


def execute_program(*, program):
    return {"accepted": bool(program)}


qubits = sc.input(
    "qubits",
    sc.SeriesType(sc.ScalarType(sc.EntityType())),
)
frequency = sc.point(
    "readout_frequency",
    sc.ScalarType(sc.QuantityType()),
)
program_type = sc.ScalarType(sc.PayloadType("lab.pulse-program.v1"))
receipt_type = sc.ScalarType(sc.PayloadType("lab.execution-receipt.v1"))

program = sc.compute(
    "build-program",
    fn=build_program,
    inputs={"qubits": qubits, "frequency": frequency},
    output_type=program_type,
)
execute = sc.compute(
    "execute-program",
    fn=execute_program,
    inputs={"program": program.output},
    output_type=receipt_type,
)

readout_module = (
    sc.module("readout")
    .inputs(qubits)
    .computes(program, execute)
    .export(receipt=execute.output)
    .product("iq")
    .build()
)

readout = readout_module.instantiate("readout", qubits=qubits)
experiment_module = (
    sc.module("readout-experiment").inputs(qubits).use(readout).build()
)
readout_template = (
    experiment_module.template("readout", kind="readout")
    .record_product(readout.products.iq)
    .build()
)
```

Use the same `frequency` handle in module bindings and
`template.scan(frequency, ...)`. Scan targets are never stringly named columns,
and authoring handles are created only by DSL factories rather than by filling
compiler-facing dataclasses.

Desired-state targets are likewise structural. Use
`bind_field(resource, capability=..., field=..., value=...)`; for table-driven
state use `state_each(..., capability=..., field=..., value=...)`. Packed paths
such as `"resource.capability.field"` are not part of the authoring API.

Values supplied through `template.bind(...)` or `Workspace.prepare(...).input(...)`
belong to a closed, recursively typed runtime-input domain (quantities, entity
references, scalar JSON values, lists, and string-keyed mappings). Arbitrary
Python objects must cross an explicit payload or artifact boundary instead of
silently entering a durable run request.

Compute functions receive only their declared inputs as keyword arguments.
Parameter lookups, routes, and upstream compute results must therefore appear
explicitly in `inputs`; no ambient runtime context is part of the authoring API.

`program.output` is an ordinary typed value, so downstream computes and child
modules consume the producer itself instead of reconstructing an edge from a
node name. A reusable module explicitly exports the values that cross its
boundary. Each named invocation then owns hygienic `outputs` and `products`
handles plus independently scoped logical resource ports, so two instances of
the same module can be wired and recorded independently. Explicit instances
must connect every declared input; shared inputs are therefore visible wiring
in the parent module rather than an accidental same-name merge. Reusable
modules declare products, while fixed records remain a template-root or scratch
experiment concern. Product selection stays at the template boundary because
it is a workflow persistence choice rather than reusable module behavior.

Before Scopecat reads configuration, it validates template shape, invocation
input types, product selection, the source compute graph, route capabilities,
record schemas, and whether each value exists at the stage and rate where it is
used. The linked typed program is verified again at the compiler boundary.
Provider descriptions and execution ABI compatibility are likewise checked
before a durable run is created; acquiring live drivers remains inside the
resource lease after run acceptance.

These boundaries are inspectable without executing a run. `template.check()`
checks only the reusable definition, `template.bind(...).check()` compiles the
complete config-free authoring graph, and `workspace.prepare(...).check()`
reports the authoring, configuration, and planning phases separately. Each
report exposes structured phase status and problems; `.explain()` renders
the same report as deterministic text for notebooks and logs. Candidate configs
are resolved read-only for system summaries, checks, validation, and previews;
only a run or an explicit activation materializes candidate evidence.

## Measurement Transformation Boundary

Core also has a lower-level typed graph for pure measurement postprocessing
between producer-neutral value ingress and durable record projection. Semantic
transform declarations retain exact logical input and output product contracts.
Port ids are transform-local semantic roles, while `ProductUseId` values are
graph wiring. Recursively immutable semantic parameters, explicit per-transform
implementation bindings, and pure typed capability validators keep transient
host callables outside the graph while rejecting unsupported interfaces before
effects. The first executable rate is point-local `POINT`, whose kernels run
once per canonical logical point and return checked values through the same
fragment assembly used by domain outputs.

This is currently an architecture and adapter boundary, not a notebook-facing
authoring DSL. Local instrument collection now has a narrow ingress seam: an
exact pre-effect binding maps the current local execution program's selected
collection subset to one value fragment. This first seam accepts only
collection-only point programs: the binding gates collected-value ingress, not
engine effect authorization, and does not yet prove state or compute context.
Although the transient program can represent a proper collection subset, the
current compiler lowering still makes that subset equal the complete logical
use inventory because `BoundPlan` requires local realization coverage for every
use. Only receipts that a trusted collection repository can resolve back to
their persisted chunks may close that fragment: operation identity, bound
command hash, and reloaded chunk content hash must all correlate before
accepted value entries enter the neutral data plane. Runtime collection
addresses are not copied into those entries; their retained selection remains
a control-plane proof over the linked plan and routing. This seam does not
replace the existing engine's point-by-point recording or crash-visible
persistence.
`POINT_SET` and cross-point execution, point-scoped neutral closure, aggregate
local/domain/transform ownership and lowering, full state/context proofs, full
engine integration, one run-provenance token carried through projection, and
proofs that a domain target implements an equivalent offloaded transform remain
later work.

## Persistence Boundary

Stored structured runs contain the normalized `RunRequest`, the accepted
configuration snapshot, the user-visible `RunPlanRecord`, and execution
evidence such as measurements, outcomes, journal transitions, and problems.
These records answer what the operator requested, what configuration was
accepted, what was planned, and what actually happened.

Experiment modules, `TypedProgram`, `BoundPlan`, and `ExecutionProgram` are
transient Python objects. They may change as the DSL, compiler, and execution
engine improve and are not durable or replayable formats. `RunPlanRecord` is a
stable projection for inspection, not an executable program. It records points,
outputs, intended state changes, and resolved resource routes; compute steps,
generated payloads, expanded driver fields, and runtime counters stay in
transient preview/execution models and execution evidence.

The durable records remain independently readable. `RunHandle.config` loads only
the accepted configuration snapshot, `RunHandle.request` loads operator intent
when the run has one, and `RunHandle.plan` loads the accepted plan record. A
missing or damaged plan record therefore does not make configuration or request
evidence unavailable, and completed runs do not recreate a transient preview.

## Examples

Run the main quantum workflow sample:

```sh
uv run python examples/quantum/notebooks/01_open_workspace.py
uv run python examples/quantum/scripts/readout_frequency.py
```

More quantum examples and their validation commands live in
`examples/quantum/README.md`.

## Design Notes

Use [docs/README.md](docs/README.md) as the entry point for long-lived design
direction, architecture boundaries, and durable data contracts.

## Development

Run the full workspace checks from the repository root:

```sh
uv run pytest
uv run basedpyright
uv run ruff check packages examples
uv run ruff format --check packages examples
```

Run narrower slices while iterating:

```sh
uv run --package scopecat pytest packages/scopecat/tests
uv run --package scopecat-quantum pytest packages/scopecat-quantum/tests
uv run pytest examples/quantum/tests
uv run pytest examples/quantum/support/tests
uv run basedpyright --project packages/scopecat
uv run basedpyright --project packages/scopecat-quantum
uv run basedpyright --project examples/quantum/support
```
