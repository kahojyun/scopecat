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

Routine configuration changes use typed intent APIs:

```python
with project.connect() as lab:
    draft = lab.config.edit().replace_scalar(
        "repetitions",
        sc.Quantity(256, "count"),
    )
    changed = lab.config.set_default(draft, note="increase averaging")

    analysis = run.analysis("fit").propose(...)
    accepted = lab.config.accept(analysis, note="fit passed")
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
and Arrow support for data that fits in notebook memory. Large runs remain
available through `run.measurement_batches(...)`; selections and exports can be
applied to each yielded batch. See the
[measurement workflow](../../docs/measurement-data.md) for details; install
`scopecat[pandas]` or `scopecat[polars]` only for the corresponding conversion.

See the [authoring dataflow](../../docs/experiment-authoring.md) for how scalar
and array shape, compute placement, returned results, and explicit recording fit
together.

See the [repository README](../../README.md) for setup and development commands,
and the [daemon model](../../docs/lab-daemon.md) for durable ownership and
fencing semantics.
