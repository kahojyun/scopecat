# Scopecat

<p align="center"><img src="assets/branding/app-icon.svg" alt="Scopecat app icon" width="160"></p>

Scopecat is a local-first Python workspace for describing experiments, running
them through dry-run, adapter, or native instrument paths, and keeping the
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
    mode="native_simulate",
    native_instrument_provider=provider,
)

experiment = lab.experiment("readout frequency", source=readout_frequency_spec)

run = lab.run(experiment)
raw = run.data().measurements()
run.attach(
    key="notebook",
    text="manual sweep notes",
    filename="manual-sweep-notes.md",
)

analysis = (
    run.analysis("manual readout review", key="readout-review")
    .input("raw-measurements", expected_kind="measurement_dataset")
    .input("notebook", role="notes", expected_kind="attachment")
    .note(f"captured {len(raw.dataset.records)} records")
    .propose(
        "drive_frequency",
        sc.set_param("drive_frequency", sc.Quantity(5.5, "GHz")),
        reason="best observed point",
    )
)
analysis.save()

candidate = analysis.candidate_config()
next_run = lab.run(experiment, config=candidate)
comparison = lab.compare(run, next_run)
overview = lab.overview(run)
```

`ExperimentSpec` and existing templates remain useful sources for experiments,
but the first post-run user path is `Run.data()`, `Run.attach(...)`, and
`Run.analysis(...)`. Attachments belong directly to the run. Analysis records
use stable keys, declare their inputs, and can be produced manually or through
an `AnalysisStep` without changing the saved record shape.

Durable `ExperimentSpec` JSON is still useful for debugging, fixtures, and
adapter-boundary tests, but it is not the preferred authoring surface for new
notebook or script users.

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
