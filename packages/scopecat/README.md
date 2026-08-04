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
@sc.experiment_factory
def local_value(experiment: sc.ExperimentContext) -> None:
    value = experiment.compute(
        "value",
        fn=lambda: 1.0,
        output_type=sc.ScalarType(sc.FloatType()),
    )
    experiment.record(value)


with project.connect() as lab:
    run = lab.run(local_value())
```

Admission, resource ownership, measurements, analysis, and configuration
history still cross the daemon boundary. Operator controls such as event replay
and attention resolution are available through `lab.control`.

`run.measurements()` exposes a canonical `xarray.Dataset` through
`measurements.xarray`; NumPy, Xarray, and Arrow support are installed with the
core package. Install `scopecat[pandas]` only when calling the explicit pandas
export adapter.

See the [repository README](../../README.md) for setup and development commands,
and the [daemon model](../../docs/lab-daemon.md) for durable ownership and
fencing semantics.
