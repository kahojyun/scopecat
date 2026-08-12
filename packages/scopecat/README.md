# Scopecat

Domain-neutral experiment authoring, planning, execution, measurement, and
notebook APIs for a local Scopecat project.

```python
import scopecat as sc

project = sc.open_project("./my-lab")
with project.connect() as lab:
    health = lab.health()
    runs = lab.runs()
```

Project discovery loads the version-controlled `LabApplication` shared with
the daemon. Its optional system builder receives the accepted configuration
snapshot selected for each run.

Routine analysis and configuration changes use typed intent APIs:

```python
with project.connect() as lab:
    run = lab.runs()[0]
    context = run.analysis("fit")
    score = fit_score(context.measurements())
    analysis = (
        context.result()
        .fact("fit-score", score)
        .propose("fit-update", update, evidence=("fit-score",))
        .save()
    )
    accepted = lab.config.accept(analysis, note="fit passed")

    draft = lab.config.edit().replace_scalar(
        "repetitions",
        sc.Quantity(256, "count"),
    )
    changed = lab.config.set_default(draft, note="increase averaging")
    restored = lab.config.undo(note="restore the previous default")
```

Interactive closures may execute in the notebook process:

```python
@sc.experiment
def local_value(experiment: sc.ExperimentContext) -> sc.ValueRef:
    return experiment.compute(
        "value",
        fn=lambda: 1.0,
        output_type=sc.ScalarType(sc.FloatType()),
    )


with project.connect() as lab:
    run = lab.run(local_value())
```

Admission, resource ownership, measurements, analysis, and configuration
history still cross the daemon boundary. Operator controls such as event replay,
safe run cancellation, and attention resolution are available through
`lab.control`.

`run.measurements()` captures an immutable analysis snapshot with NumPy, Xarray,
and Arrow support for data that fits in notebook memory. Large runs can use a
projected
`run.measurements().project(...).to_record_batch_reader(...)` finite Arrow
reader. See the
[measurement workflow](../../docs/how-to/use-measurement-data.md) for details; install
`scopecat[pandas]` or `scopecat[polars]` only for the corresponding conversion.

See the [authoring dataflow](../../docs/concepts/experiment-dataflow.md) for how scalar
and array shape, compute placement, returned results, and explicit recording fit
together.

See the [repository README](../../README.md) for setup and development commands,
and the [daemon model](../../docs/development/architecture/daemon.md) for durable ownership and
fencing semantics.
