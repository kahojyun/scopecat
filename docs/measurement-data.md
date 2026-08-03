# Measurement data workflows

Scopecat keeps the experiment declaration, durable measurement records, and
analysis view connected by one labeled schema. Users declare what a result
means once, at the instrument or experiment boundary; recording, the GUI, and
dataframe or array exports consume that same information.

## Define what should be recorded

Acquisition result declarations own field roles, data types, units, and local
axes. Recording the typed result bundle preserves those relationships:

```python
trace = vna.sweep()
experiment.record(trace)
```

The declared frequency coordinate and response observable remain separate
dataset variables, share their recording group and sample dimension, and retain
their units. Use `record(...)` on one bundle member only when that member alone
is the intended durable data. Experiment authors should not repeat a schema or
manually join coordinate and observable names.

Scalar inputs, parameters, and point coordinates may also be recorded. The
resulting schema always has a `point` dimension; acquisition-local axes follow
it in each variable's dimension list.

## Choose the point-domain shape explicitly

A product grid is appropriate when independent axes should form a Cartesian
scan:

```python
experiment.scan(sc.axis(bias, (-0.2, 0.0, 0.2)))
experiment.scan(sc.axis(power, (-30.0, -20.0)))
```

Use explicit rows when points are correlated, sparse, duplicated, or otherwise
do not form a rectangular product:

```python
experiment.points(
    (
        {bias: -0.20, power: -30.0},
        {bias: -0.05, power: -24.0},
        {bias: -0.05, power: -24.0},  # repeated measurements are valid
        {bias: 0.18, power: -17.0},
    )
)
```

Every row must contain the same typed coordinate columns. Row order and
duplicates are preserved, and each row receives its own logical point identity.
Grid axes and explicit point rows cannot be mixed in one experiment because
they describe two different domain semantics. For an empty explicit domain,
pass its columns with `experiment.points((), coordinates=(bias, power))`.

Explicit rows are materialized before execution. When the next point depends on
measurements from an earlier point, use a bounded staged experiment:

```python
def choose_next(stage):
    data = stage.run.measurements()
    candidate = optimizer.ask(data)
    return None if candidate is None else point_experiment(candidate)

sequence = lab.run_staged(
    point_experiment(initial_point),
    next_stage=choose_next,
    max_stages=20,
)
```

Each stage is an ordinary durable run. It uses the same resolved configuration
snapshot and records typed sequence id, stage index, and predecessor run id in
both its request and manifest. The callback may inspect the current run and all
prior runs through `stage.run` and `stage.history`; returning `None` finishes
naturally, while `max_stages` bounds an optimizer that keeps proposing points.
Reaching that bound does not call the callback for the final completed stage,
so a stateful optimizer is not advanced past durable work.

Sequences can be rediscovered after restarting a notebook. Discovery pages
through run manifests rather than loading every run request:

```python
sequences = lab.staged_experiments()  # newest sequence first
sequence = lab.get_staged_experiment(sequences[0].sequence_id)

continued = lab.resume_staged(
    sequence.sequence_id,
    next_stage=choose_next,
    max_stages=10,  # bounds newly executed stages
)
```

For a rediscovered sequence, `stopped_by_limit` is `None`: individual runs and
their lineage are durable, but the earlier notebook loop's stop reason is not.

Resume calls `choose_next` with the latest durable stage before executing new
work, including the callback deferred when the earlier execution reached
`max_stages`. Its own limit again defers the callback for its final stage until
another resume. New stages inherit the latest accepted config snapshot and
source, ordinary request metadata, and operator. Resuming requires the latest
run to have completed successfully. This workflow deliberately favors
notebook-driven adaptive work over a hidden intra-run control loop.

The schema records whether the domain is a `product_grid` or `point_cloud`.
Consumers should use that semantic layout instead of trying to infer a grid
from coincidentally regular values.

## Represent variable-length results without padding

An acquisition axis with no fixed extent is ragged:

```python
@acquisition(axes={"sample": axis()})
def capture_until_trigger(self) -> CaptureResults: ...
```

Each point may return a different number of samples. Scopecat still validates
the declared rank, data type, and unit; only the extent of the ragged dimension
is allowed to vary. Use `axis(size=1024)` for a fixed extent or a state field
such as `axis(size="points")` when configuration determines one fixed extent.

Ragged arrays stay nested per point in durable records and Arrow. They are not
silently padded with sentinel values. Xarray export uses an indexed observation
dimension with parent-point and local-index coordinates, making the flattening
explicit and reversible. Pandas point layout keeps each array in one cell;
`layout="long"` emits one row per local sample.

If an unavailable value propagates through a postprocessor before a ragged
extent can be observed, its shape keeps `None` for that unknown axis rather
than inventing a length. Xarray can recover the point-local layout from an
available coordinate or observable in the same recording group. When no
aligned sibling knows the extent, the point contributes zero observations and
retains an explicit unknown extent.

Domain-program result axes remain fixed-size. Variable-length axes currently
belong to typed instrument acquisitions, where every returned value is checked
before entering the measurement stream.

## Read and slice measurements in notebooks

`run.measurements()` returns the labeled analysis facade directly:

```python
data = run.measurements()

data.coords                    # coordinate variables by id
data.data_vars                 # observable variables by id
data["readout.dc_bias"].values

near_zero = data.sel(
    **{"readout.dc_bias": sc.Quantity(0.0, "V")},
    method="nearest",
)
subset = data.isel(point=slice(0, 20), sample=slice(10, 50))
ragged_window = data.isel_ragged(
    sample=slice(10, 50),
    group="readout",
)
valid = data.where(data["temperature"].is_available())
groups = data.groupby("amplification")
```

Exact selection retains every matching row, including duplicate point-cloud
coordinates. Numeric coordinate selection accepts unit-aware quantities and an
optional nearest tolerance. `isel(...)` accepts the point dimension and any
fixed local dimension without dropping dimensions. `isel_ragged(...)` applies
the indexer independently inside each point and requires either a recording
group, which keeps its variables aligned, or one ungrouped variable. Boolean
masks compose with `&`, `|`, and `~`.

Large runs can be consumed without materializing every record at once:

```python
for batch in run.measurement_batches(batch_size=500):
    analyze(batch)
```

Each batch is the same labeled `Dataset` facade, so slicing and ecosystem
exports work unchanged. Its `point` dimension is the number of records in that
batch, while durable `point_index` values remain absolute. Metadata exposes
`scopecat_batch_offset` and `scopecat_planned_point_count`. An empty run yields
one zero-row, schema-bearing batch so callers can still inspect variables and
initialize downstream tables.

The same view connects to common analysis ecosystems:

Install the `scopecat[data]` extra to enable these optional adapters.

```python
xds = data.to_xarray()
table = data.to_arrow()
frame = data.to_pandas()                  # one row per experiment point
long_frame = data.to_pandas(layout="long")
```

Complex values remain complex in Xarray and pandas and become explicit
`{real, imag}` structs in Arrow. Ragged variables in the same recording group
share one Xarray observation dimension and retain `parent_point_index` and local
index coordinates; ungrouped ragged variables remain independent. Unavailable
values remain null or missing and gain a companion `__unavailable_reason`
variable or column. The durable Pydantic dataset remains available through
`data.raw` when low-level inspection is actually needed.

## Let the GUI use experiment knowledge

The complete planned schema is registered once in the canonical dataset header
before the first measurement append. The GUI can therefore render live or empty
datasets without waiting for terminal metadata and without guessing solely from
JSON values. Automatic plots use:

- coordinate versus observable roles and primary-variable ordering;
- dimensions and recording groups to pair trace coordinates with samples;
- labels and units for axes and table columns;
- data type information, exposing complex magnitude, phase, real, and imaginary
  views explicitly; and
- point-domain layout, using the first two authored real numeric axes of a
  product grid as heatmap x/y, scatter for point clouds, and a line only for a
  monotonic grid coordinate.

Point-scalar observables become coordinate plots; point-local rank-one arrays
become trace series. A point cloud with two scalar coordinate columns also gets
an x/y scatter whose color encodes each scalar observable. For a
higher-dimensional product grid, every remaining authored axis becomes a fixed
slice shown in the selector and caption. Each observed slice is validated
independently: it must contain exactly one cell for every x/y pair, with no
missing or duplicate coordinates. An invalid slice falls back to scalar/table
views instead of presenting a misleading surface. If a candidate produces more
than 32 actual slices, the GUI disables heatmaps for the whole candidate and
uses the same scalar/table fallback. Complex heatmaps offer magnitude, phase,
real, and imaginary color modes. When several safe views exist, the GUI lists
every candidate in a selector instead of silently truncating them. Shapes that
do not have a safe automatic visual remain in the typed table, with raw records
available as a secondary expandable view. This keeps automatic plotting useful
without pretending that every tensor has one obvious chart.
