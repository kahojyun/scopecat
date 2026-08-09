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
it in each variable's dimension list. Symbolic values default to observables;
pass `role="coordinate"` when an expression derives an independent physical
coordinate.

An experiment that intentionally scans an LO should record its physical RF
coordinate at authoring time instead of requiring an analysis script to
reconstruct the x-axis. A signed IF keeps the lab convention explicit:

```python
lo = experiment.scan("lo_frequency", (4.9, 5.0, 5.1), unit="GHz")
signed_if = sc.Quantity(-100, "MHz")
rf = lo + signed_if
experiment.record(
    rf,
    record_id="rf_frequency",
    role="coordinate",
    metadata={
        "relation": "rf_frequency = lo_frequency + signed_if",
        "signed_if_hz": float(signed_if.to("Hz").value),
    },
)
```

The LO scan is already recorded as a point coordinate. The extra record makes
RF directly available to plots while the metadata preserves how it was derived.
This pattern can live in the few lab experiments that need it; the measurement
model does not need a mixer-specific frequency-plan type.

## Choose the point-domain shape explicitly

A product grid is appropriate when independent axes should form a Cartesian
point domain. For the common case, each `scan()` call infers and returns the
typed coordinate consumed by the experiment body:

```python
import numpy as np

bias = experiment.scan(
    "bias",
    (-0.2, 0.0, 0.2),
    unit="V",
)
source_power = experiment.scan(
    "source_power",
    np.linspace(-30.0, -20.0, 21),
    unit="dBm",
)
```

The returned `bias` and `source_power` values can be passed directly to
instrument, module, or domain-program inputs. Repeated calls accumulate axes in
declaration order.

For an explicitly editable point plan, declare coordinates and axes separately.
Generated axes choose either inclusive start and stop coordinates or a center
and full coordinate width:

```python
power = sc.coordinate(
    "source_power",
    sc.QuantityType(unit="dBm"),
)
start_stop_power = sc.axis(
    power,
    start=sc.Quantity(-30.0, "dBm"),
    stop=sc.Quantity(-10.0, "dBm"),
    points=41,
)
centered_power = sc.axis(
    power,
    center=sc.Quantity(-20.0, "dBm"),
    span=sc.Quantity(6.0, "dBm"),
    points=13,
)
```

Both generated forms include their endpoints and space coordinates evenly in
the selected coordinate unit. A dBm axis stays in dBm rather than being
converted to W. In the centered form, `span` is the full coordinate width, so
the example above runs from -23 dBm through -17 dBm.

Use explicit rows when points are correlated, sparse, duplicated, or otherwise
do not form a rectangular product:

```python
bias = sc.coordinate(
    "bias",
    sc.QuantityType(unit="V"),
)
experiment.points(
    (
        {
            bias: sc.Quantity(-0.20, "V"),
            power: sc.Quantity(-30.0, "dBm"),
        },
        {
            bias: sc.Quantity(-0.05, "V"),
            power: sc.Quantity(-24.0, "dBm"),
        },
        {  # repeated measurements are valid
            bias: sc.Quantity(-0.05, "V"),
            power: sc.Quantity(-24.0, "dBm"),
        },
        {
            bias: sc.Quantity(0.18, "V"),
            power: sc.Quantity(-17.0, "dBm"),
        },
    )
)
```

Every row must contain the same typed coordinate columns. Row order and
duplicates are preserved, and each row receives its own logical point identity.
Grid axes and explicit point rows cannot be mixed in one experiment because
they describe two different domain semantics. For an empty explicit domain,
pass its columns with `experiment.points((), coordinates=(bias, power))`.

Explicit rows are materialized before execution. When each new point depends on
earlier measurements, use a bounded, resumable
[staged experiment](adaptive-experiments.md) instead of a hidden intra-run
control loop.

The current planner materializes both explicit rows and product-grid points
before admission. The [scalability benchmarks](scalability-benchmarks.md) track
that operating envelope; row order, logical ordinals, schema, and result identity
remain its stable semantics.

The schema records whether the domain is a `product_grid` or `point_cloud`.
Consumers should use that semantic layout instead of trying to infer a grid
from coincidentally regular values.

Logical points describe experiment conditions. Repeated shots, measured
entities or channels, and instrument-native sample axes contribute separate
workload dimensions and retain their structure in acquisition results. A VNA
frequency trace, digitizer waveform, or per-shot readout array can therefore
grow independently of the outer point domain instead of being flattened into
control-plane points. This keeps batching, storage, slicing, and visualization
aligned with the physical acquisition.

## Repeat, traverse, and edit a point plan

Grid definitions can declare repeat and physical traversal policy alongside
their axes:

```python
experiment.grid(
    sc.axis(bias, (-0.2, 0.0, 0.2), unit="V"),
    sc.axis(power, (-30.0, -25.0, -20.0), unit="dBm"),
    repeat=4,
    repeat_mode="point",
    traversal="snake",
)
```

`repeat_mode="point"` measures each base point four times before moving on.
`repeat_mode="sweep"` repeats the complete sweep. Counts above one add a typed
`repeat` coordinate, so repeated measurements remain distinct. Snake traversal
reduces product-grid retracing: with sweep repeats, a one-dimensional sweep
alternates direction, while a multidimensional grid reverses adjacent paths. It
changes physical execution order only; logical point ids and durable dataset
rows stay canonical.

An invocation exposes orthogonal immutable edits:

```python
edited = (
    spectroscopy()
    .bind(sample="q0")
    .with_axis(sc.axis(power, (-35.0, -30.0, -25.0), unit="dBm"))
    .without_axis(bias)
    .with_repeat(3, mode="sweep")
    .with_traversal("snake")
)

definition_default = edited.reset_points()
```

`.grid(...)` and `.points(...)` replace the complete domain while retaining the
repeat policy. Grid replacement retains traversal; explicit points always run
in row order and therefore restore forward traversal. `.with_axis(...)` replaces
an axis in place or appends a new one; `.without_axis(...)` applies only to a
grid. `reset_points()` discards all invocation point-plan edits and restores the
definition default.

For a deterministic randomized order, shuffle rows with an explicit seed and
pass them to `.points(...)`. For measurement-dependent point selection, use a
staged experiment rather than adding another point-plan control language.

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

Ragged arrays retain an explicit point-local shape and are never padded with
sentinel values. Their Xarray observation dimension carries parent-point and
local-index coordinates, so flattening remains explicit and reversible.
Pandas point layout keeps each array in one cell; `layout="long"` emits one row
per local sample.

In Python, available `MeasurementArray.values` is a read-only, C-contiguous
NumPy array with the declared dtype. JSON and API representations remain nested;
complex leaves use `{real, imag}` objects.
`MeasurementScalar.value` is likewise normalized to its declared Python type;
`complex128` is a native `complex` at runtime and the same `{real, imag}` object
on the wire.

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

data.xarray  # independent copy of the cached xr.Dataset
data.coords  # coordinate variables by id
data.data_vars  # observable variables by id
data.point_indices  # durable identities in current row order
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

Analysis steps receive the same facade through `context.measurements()`. The
separate `run.data()` handle is for listing stored content and reading
artifacts; it is not a second measurement API.

Exact selection retains every matching row, including duplicate point-cloud
coordinates. Numeric coordinate selection accepts unit-aware quantities and an
optional nearest tolerance. `isel(...)` accepts the point dimension and any
fixed local dimension without dropping dimensions. `isel_ragged(...)` applies
the indexer independently inside each point and requires either a recording
group, which keeps its variables aligned, or one ungrouped variable. Boolean
masks compose with `&`, `|`, and `~`. Fixed-shape `isel`, `sel`, `where`, and
`groupby` use Xarray's indexing, alignment, nearest-selection, and grouping
semantics, then map the selected positions back to durable records. Direct
Xarray operations are suitable when the result should stay entirely inside the
Xarray ecosystem and all dimensions are fixed. Indexed ragged observations are
different: `data.xarray.isel(point=...)` selects point-aligned metadata but does
not cascade to the separate observation dimension. Use the facade's
`data.isel(point=...)` before exporting, and use `isel_ragged(...)` for local
ragged dimensions, so parent observations stay aligned.

Large runs can be consumed without materializing every record at once:

```python
for batch in run.measurement_batches(batch_size=500):
    analyze(batch)
```

Each batch is the same labeled `Dataset` facade, so slicing and ecosystem
exports work unchanged. Its `point` dimension is the number of records in that
batch, while durable `point_index` values remain absolute. Metadata exposes
`scopecat_batch_offset`; the immutable schema continues to describe the complete
planned point domain and its point count. An empty run yields one zero-row,
schema-bearing batch so callers can still inspect variables and initialize
downstream tables.

Xarray and Arrow are core dependencies and are available on every measurement
view. Install the `scopecat[pandas]` extra only for explicit pandas exports:

```python
xds = data.to_xarray()  # explicit conversion spelling
another = data.xarray  # equivalent property shorthand
assert xds is not another  # snapshots never share identity
grid = data.to_xarray(layout="grid")  # complete product grids only
table = data.to_arrow()
frame = data.to_pandas()  # one row per experiment point
long_frame = data.to_pandas(layout="long")
```

These complete conversions materialize the selected measurement snapshot and
are intended for datasets that fit in notebook memory. For larger runs,
`run.measurement_batches(...)` is the bounded notebook read path; select within
each yielded batch before exporting it.

The default Xarray layout keeps the durable `point` row dimension, which also
works for point clouds, live batches, partial selections, and ragged results.
For a complete product-grid dataset, `layout="grid"` restores the authored
product axes as dimensions in C/product order and reshapes point-aligned scalar
and array variables onto them. It rejects partial grids, duplicate or missing
point ordinals, and coordinates that disagree with their declared grid axis
instead of silently reshaping the wrong rows.

Complex values remain complex in Xarray and pandas and become explicit
`{real, imag}` structs in Arrow. Ragged variables in the same recording group
share one Xarray observation dimension and retain `parent_point_index` and local
index coordinates; ungrouped ragged variables remain independent. Every ragged
variable has an observation-aligned `<variable>__observation_valid` mask. When
values are unavailable, `<variable>__observation_unavailable_reason` identifies
the affected observations, while the existing `<variable>__unavailable_reason`
retains the point-level reason. This makes integer, boolean, and string fill
values unambiguous.

Durable measurement values and metadata are deeply immutable. Each
`data.xarray` or `to_xarray()` result is an independent snapshot, so caller
edits cannot affect later selections or exports. Empty and entirely unavailable
columns still retain their declared Arrow types.

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
slice selector. Axis values are persisted in the canonical header, so selectors
are available before a run completes and show typed values with units. Duplicate
or opaque fixed-axis values remain selectable by their authored index. Axes with
more than 256 values use a one-based index input instead of rendering thousands
of browser options.

Automatic product-grid plots load only the selected slice. Heatmaps require
exactly one value for every x/y cell; incomplete live data is labeled instead
of being presented as a complete surface. Automatic slices are bounded to 4,096
points, while trace previews are bounded to 32 series and 4,096 plotted samples.
Larger data remains available through notebook batch reads. Complex heatmaps offer
magnitude, phase, real, and imaginary color modes. When several safe views
exist, the GUI lists every candidate in a selector instead of silently
truncating them. Shapes that do not have a safe automatic visual remain in the
typed table, with raw records available as a secondary expandable view. This
keeps automatic plotting useful without pretending that every tensor has one
obvious chart.

Trace previews select one recording group or observable and may fix authored
product-grid axes by index. Complex values support magnitude, phase, real, and
imaginary modes; real values use their direct value. Unavailable points are
skipped until the requested number of usable series is reached or the selection
is exhausted.

## Save analysis results as typed views

Analysis outputs use the same explicit presentation contract instead of saving
arbitrary JSON under a `table` or `figure` label. Tables declare ordered
columns, labels, and units; figures declare numeric axes and embedded line or
scatter series:

```python
result = (
    context.result("Resonator fit")
    .input(measurements.entry.id, role="fit-input")
    .table(
        sc.AnalysisTable.from_rows(
            fit_rows,
            columns=(
                sc.AnalysisTableColumn(id="bias_v", label="Bias", unit="V"),
                sc.AnalysisTableColumn(
                    id="frequency_ghz",
                    label="Resonance",
                    unit="GHz",
                ),
            ),
        ),
        title="Fit parameters",
    )
    .figure(
        sc.AnalysisFigure(
            kind="line",
            x_axis=sc.AnalysisFigureAxis(label="Bias", unit="V"),
            y_axis=sc.AnalysisFigureAxis(label="Resonance", unit="GHz"),
            series=[
                sc.AnalysisFigureSeries.from_arrays(
                    id="fit",
                    x=bias_values,
                    y=resonance_values,
                )
            ],
        ),
        title="Resonance fit",
    )
)
```

`AnalysisTable.from_rows(...)` and
`AnalysisFigureSeries.from_arrays(...)` materialize NumPy-style scalar and
array values at the authoring boundary. The durable models then enforce finite,
GUI-safe scalar and point budgets. The run view renders these outputs as an
accessible table and SVG figure and retains the declared analysis inputs and
metadata as provenance; proposal outputs remain typed references to their
separately persisted proposal records.
