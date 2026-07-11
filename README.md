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
    instrument_provider=provider,
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
    .build()
)
```

Use the same `frequency` handle in module bindings and
`template.scan(frequency, ...)`. Scan targets are never stringly named columns,
and authoring handles are created only by DSL factories rather than by filling
compiler-facing dataclasses.

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
node name.

## Persistence Boundary

Stored structured runs contain the normalized `RunRequest`, the accepted
configuration snapshot, the user-visible `RunPlanRecord`, and execution
evidence such as measurements, outcomes, and diagnostics. These records answer
what the operator requested, what configuration was accepted, what was planned,
and what actually happened.

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
uv run pytest examples/quantum/tests
uv run pytest examples/quantum/support/tests
uv run basedpyright --project packages/scopecat
uv run basedpyright --project examples/quantum/support
```
