# Measurement data workflows

Scopecat keeps the experiment declaration, durable measurement records, and
analysis view connected by one labeled schema. Users declare what a result
means once, at the instrument or experiment boundary; recording, the GUI, and
dataframe or array exports consume that same information.

## Return what should be recorded

Acquisition result declarations own field roles, data types, units, and local
axes. Returning the typed result bundle preserves those relationships:

```python
trace = vna.sweep()
return trace
```

The declared frequency coordinate and response observable remain separate
dataset variables, share their recording group and sample dimension, and retain
their units. Return one bundle member when that member alone is the intended
durable data. Experiment authors should not repeat a schema or manually join
coordinate and observable names.

Scalar inputs, parameters, and point coordinates may also be returned. The
resulting schema always has a `point` dimension; acquisition-local axes follow
it in each variable's dimension list. Symbolic values default to observables;
use an explicit `record(..., role="coordinate")` only when an expression derives
an independent physical coordinate.

`run.result(authored_output)` binds the same returned `ProductRef`, `ValueRef`,
and coordinate handles used during authoring. `run.result()` instead reads the
persisted return paths without rebuilding the original experiment. Both retain
the completed `Dataset` as `.dataset`; `RecordRef` is only needed to select one
of several explicitly recorded aliases. See the
[authoring dataflow](experiment-authoring.md) for the complete model.

The persisted dataset schema carries the versioned result contract mapping each
return path to its variable. Symbolic handles are an optional typed convenience
rather than historical schema authority.

A specialized LO scan can return its physical RF coordinate with coordinate
policy, making the dataset immediately plot-ready. A signed IF keeps the lab
convention explicit:

```python
@dataclass(frozen=True)
class SpectrumResult:
    rf_frequency: Annotated[
        sc.ValueRef[sc.Quantity],
        sc.Result(
            role="coordinate",
            metadata={
                "relation": "rf_frequency = lo_frequency + signed_if",
                "signed_if_hz": -100_000_000.0,
            },
        ),
    ]


lo = experiment.scan("lo_frequency", (4.9, 5.0, 5.1), unit="GHz")
rf = lo + sc.Quantity(-100, "MHz")
return SpectrumResult(rf_frequency=rf)
```

The LO scan is already a point coordinate. The derived record makes RF directly
available to plots while metadata preserves how it was computed. A small
lab-local helper can reuse this pattern across the spectroscopy experiments that
need it.

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

Explicit rows are materialized before execution. When each new run depends on
earlier measurements, use a bounded, resumable [run sequence](run-sequences.md).
Measurement-dependent points inside one executing run require a separate
adaptive point-plan abstraction rather than a hidden control loop.

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
pass them to `.points(...)`. Measurement-dependent point selection inside one
run is intentionally not modeled as a run sequence or another static point-plan
control language.

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

If an unavailable value propagates through measured-data compute before a ragged
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

When analysis starts from the experiment's return value, the equivalent typed
path does not require constructing masks:

```python
result = run.result(experiment().output)
complete = result.where_available(result.output.temperature)
rows = complete.rows(build_fit_row)
```

Omitting fields requires every returned field to be available. Historical result
views accept persisted paths instead. Point-local measurement compute already
propagates unavailable inputs without invoking user kernels; these result filters
make dropping incomplete points a visible dataset-analysis decision.

Analysis steps receive the same facade through `context.measurements()`. The
separate `run.data()` handle is for listing stored content and reading
artifacts; it is not a second measurement API.

Before handing data to an ecosystem library, bind the external names and units
once with `project(...)`. Selectors may be durable variable ids, typed result
handles, or persisted result paths:

```python
projected = result.project(
    {
        "bias_v": result.output.dc_bias,
        "temperature_mk": result.output.temperature,
        "s21": result.output.trace.s_parameter,
    },
    units={"bias_v": "V", "temperature_mk": "mK"},
    diagnostics="reason",
)

arrow = projected.to_arrow()
pandas_frame = projected.to_pandas()
polars_frame = projected.to_polars()
xarray_dataset = projected.to_xarray()
```

This small projection is the adapter boundary, not an analysis framework. Fit,
filter, group, and plot with pandas, Polars, Xarray, NumPy, SciPy, or another
library after conversion. `ProjectionSchema` retains each external name's
durable variable id, typed-result path, dtype, dimensions, role, unit, label,
and recording group. Arrow repeats those semantics in field and schema
metadata, so an adapter does not have to infer them from values.

The conversion rules are deliberately fixed:

| Scopecat value | Arrow / Polars | pandas `numpy` backend | Xarray |
|---|---|---|---|
| point scalar | declared scalar type | native scalar column | `point` variable |
| point-local array | fixed or variable list | NumPy array per row | named local dimensions |
| `complex128` | `{real, imag}` struct | native complex scalar/array | native complex array |
| unavailable | null plus optional diagnostics | missing value plus optional diagnostics | fill value plus optional diagnostics |

`to_pandas()` defaults to familiar NumPy/native values. Use
`to_pandas(dtype_backend="pyarrow")` when pandas should retain Arrow extension
dtypes. `with_diagnostics("reason")` always emits one
`<name>__unavailable_reason` column per selected field, even when the current
batch has no unavailable values; `"full"` also emits JSON metadata. This keeps
schemas identical across batches. In normal construction this is spelled
`diagnostics="reason"`; identity columns are included by default and can be
omitted with `identity=False`.

Projection configuration is normally supplied atomically, so generated names
are validated against the final identity, diagnostics, and layout policy:

```python
observations = result.project(
    {
        "bias": result.output.dc_bias,
        "frequency": result.output.trace.frequency,
        "s21": result.output.trace.s_parameter,
    },
    units={"bias": "V", "frequency": "Hz"},
    diagnostics="reason",
    identity=True,
    layout="observations",
)
```

`layout="points"` keeps one row per experiment point and represents local
arrays as nested Arrow columns or NumPy arrays in pandas. The explicit
`"observations"` layout expands one aligned local-array group into scalar rows:
point-scalar fields are broadcast, every local dimension gets a
`<dimension>_index` column, and array coordinates and observables stay aligned.
Arrays must use identical local dimensions and one recording group; incompatible
selections are rejected rather than independently exploded. A usable sibling
array may supply the local extent for an unavailable ragged value.

For the pandas NumPy backend, scalar `int64`, boolean, and string projections
always use pandas `Int64`, `boolean`, and `string` extension dtypes, including
batches that happen to contain no nulls. Floating values use `float64`; the
diagnostic column distinguishes an unavailable null/NaN from an available
scientific NaN. Complex values remain native Python/NumPy complex values, with
`None` retained for unavailable scalar observations.

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

An already loaded snapshot can be split without changing its dataset identity:

```python
for batch in run.measurements().batches(batch_size=500):
    analyze(batch)
```

This convenience does not reduce the memory needed to load the notebook
snapshot. For a storage-bounded notebook read, project directly into Arrow:

```python
reader = run.measurement_record_batches(
    columns={
        "bias_v": result.output.dc_bias,
        "s21": result.output.trace.s_parameter,
    },
    units={"bias_v": "V"},
    diagnostics="reason",
    batch_size=500,
)
for record_batch in reader:
    analyze_arrow(record_batch)
```

Each typed batch uses the same labeled `Dataset` facade, so slicing and
ecosystem exports work unchanged. Its `point` dimension is the number of
records in that batch, while durable `point_index` values remain absolute.
Metadata exposes `scopecat_batch_offset` and `scopecat_snapshot_size`; the
immutable schema continues to describe the complete planned point domain and
its point count. An empty dataset yields one zero-row, schema-bearing batch so
callers can still inspect variables and initialize downstream tables.

`measurement_record_batches(...)` is the Arrow-native bounded read. Typed refs
and external names are resolved once against the manifest, and
the aliases, units, diagnostics, identity columns, and layout travel as one
projection request. The daemon decodes only the selected durable variables from
the stored Arrow append chunks, performs the projection, and returns Arrow IPC
streams rather than JSON measurement models. The first page establishes one
`RecordBatchReader.schema`; later pages are fetched only as the reader advances.
An empty run has a schema and no record batches.

Column pushdown currently stops at the immutable append-blob boundary: an
intersecting IPC blob is read as a unit, while unselected variables skip model
decoding and never cross the daemon transport. Physical per-column object-store
I/O would require a seekable file or a different chunk layout and should be
chosen from measured run sizes rather than added to the authoring model now.

`batch_size` bounds stored experiment points. With `layout="observations"`, one
point can expand into multiple observation rows; the returned reader still
splits those rows into bounded Arrow record batches. This API is a finite,
non-following read of the currently durable dataset, not a live subscription.
Its first page pins the current durable point count and every later page uses
that same append watermark, so points arriving during iteration belong to a
later read instead of silently extending the current one. Run-progress
triggers, retries, and workflow-owned live analysis state remain part of a
future workflow streaming contract.

Xarray and Arrow are core dependencies and are available on every measurement
view. Install `scopecat[pandas]` or `scopecat[polars]` for the corresponding
tabular export:

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
`run.measurement_record_batches(...)` is the bounded projected notebook read
path. Registered analysis implementations can instead declare
`data_access="batches"`; `context.trace(...)` then supplies finite typed
`Dataset` pages from the exact measurement input without materializing its full
contents. `Dataset.batches(...)` only splits an already loaded detached
snapshot when used directly.

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
or opaque fixed-axis values remain selectable by their authored index. Large
axes use an index input so the browser does not render an unbounded option list.

Automatic product-grid plots load only the selected slice. Heatmaps require
exactly one value for every x/y cell; incomplete live data is labeled instead
of being presented as a complete surface. Automatic slices and trace previews
use bounded server projections; larger data remains available through notebook
batch reads. The projection functions and UI constants own the current limits.
Complex heatmaps offer magnitude, phase, real, and imaginary color modes. When
several safe views exist, the GUI lists every candidate in a selector. Shapes
without a safe automatic visual remain in the typed table, with raw records
available as a secondary expandable view.

Trace previews select one recording group or observable and may fix authored
product-grid axes by index. Complex values support magnitude, phase, real, and
imaginary modes; real values use their direct value. Unavailable points are
skipped until the requested number of usable series is reached or the selection
is exhausted.

## Save analysis results as typed publications

Analysis results become durable only when they are explicitly published. A
typed dataclass can declare column presentation once, and both tables and
figures project that same aligned data:

```python
@dataclass(frozen=True)
class FitPoint:
    bias: Annotated[
        sc.Quantity,
        sc.AnalysisField(id="bias_v", label="Bias", unit="V"),
    ]
    resonance: Annotated[
        sc.Quantity,
        sc.AnalysisField(id="frequency_ghz", label="Resonance", unit="GHz"),
    ]


fits = fit_resonator(measurements)
fit_table = sc.AnalysisTable.from_objects(fits)
result = (
    context.result("Resonator fit")
    .table(
        fit_table,
        title="Fit parameters",
    )
    .figure(
        sc.AnalysisFigure.from_table(
            fit_table,
            kind="line",
            x="bias_v",
            y="frequency_ghz",
        ),
        title="Resonance fit",
    )
)
```

When analysis is naturally expressed in pandas, Polars, Xarray, or Arrow, keep
using that library. Give the native result one analysis-local name at the
publication boundary instead of translating it into bespoke row dataclasses:

```python
def fit_with_polars(measurements):
    frame = measurements.project(
        {"bias": "dc_bias", "response": "signal"},
        units={"bias": "V"},
        identity=False,
    ).to_polars()
    fitted = frame.with_columns(
        (pl.col("response") * 2).alias("score"),
    )
    return fitted


fits = fit_with_polars(measurements)
review = (
    context.result("Fit review")
    .dataset(
        "fits",
        fits,
        fields={
            "bias": sc.AnalysisField(role="coordinate", unit="V"),
            "response": sc.AnalysisField(unit="ratio"),
            "score": sc.AnalysisField(unit="ratio", label="Fit score"),
        },
    )
    .table(dataset="fits", columns=("bias", "score"), title="Fit rows")
    .figure(dataset="fits", kind="line", x="bias", y="score")
)
```

`dataset(...)` accepts the native object and normalizes it once. A sparse
`fields` mapping overrides metadata inherited from a measurement projection,
Arrow fields, or Xarray variables. Each `AnalysisField` can assign one stable
`id`, coordinate/observable `role`, `unit`, and `label`; unlisted fields keep
their native names and inherited semantics. The durable schema retains the
source-to-stable name mapping. A pandas default
`RangeIndex` is dropped; a named or otherwise meaningful index becomes
coordinate columns unless `index="drop"` is requested. Tables and figures only
extract their selected scalar columns, so unrelated array-valued columns remain
in the durable dataset without making a view invalid.

Xarray normalization is intentionally narrower than `to_dataframe()`: a
Dataset must have one named dimension and every coordinate and data variable
must use that dimension exactly. Scopecat records the dimension plus dataset and
variable attributes and can reconstruct it with `DerivedDataset.to_xarray()`.
Multi-dimensional or mixed scalar/array datasets are not flattened implicitly;
publish a deliberate tabular projection, or serialize the native Dataset and
publish it with `artifact(...)` until a lossless first-party layout exists.

When a table or figure uses `dataset="fits"`, its durable view retains that
analysis-local dataset ID and the selected column roles. The embedded table or
figure is a bounded preview cache for immediate rendering, not a second
authoritative scientific result. Passing rows directly still creates a
standalone preview; publish a dataset first when the relation should remain
queryable.

Persistence writes one content-addressed Arrow IPC dataset and keeps only its
reference in the analysis record. It can be loaded later without losing the
Arrow schema:

```python
fits = run.derived_dataset("analysis-fit-review-fits")
pandas_frame = fits.to_pandas()
polars_frame = fits.to_polars()
```

Use `context.trace(...)` when an analysis execution needs retained runtime
metadata, registered codecs, deterministic provenance, or bounded batch access:

```python
fits = context.trace(fn=fit_with_polars, measurements=measurements)
review = (
    context.result("Fit review")
    .dataset(
        "fits",
        fits,
        fields={"bias": sc.AnalysisField(role="coordinate")},
    )
    .fact("maximum-score", float(fits["score"].max()))
)
```

`trace(...)` still returns the native value and does not publish it by itself.
The explicit `dataset(...)` or `fact(...)` call decides the durable interface;
when its content and codec exactly match the traced result, Scopecat records an
exact `produced_by` link automatically. If `fields` or a pandas index policy
changes the normalized dataset identity, it records `derived_from` with that
first-party adapter contract instead. A table or figure remains a projection,
and points to a published dataset when that scientific relation should be
durable. Ordinary NumPy, pandas, Polars, or Xarray code can skip `trace(...)`
entirely.

When one registered function naturally returns a fit object with several
publishable results, declare stable leaf names with
`outputs={"resonance": "resonance", "residuals": "residuals"}` on its
implementation. `trace(...)` still returns that native object, while each
declared leaf receives an independent trace identity. Publishing a matching
leaf links it automatically; only equal-valued leaves need the explicit
`source=(execution_id, output_name)` disambiguation argument.

A traced function may also return exact `bytes` or a file `Path`. Publishing
that content with `artifact(...)` retains the execution link while keeping the
filename and media type as publication choices.

An analysis step returns that declarative `Analysis` value. Running the step
publishes it and returns one durable outcome; there is no additional save call:

```python
analysis = run.analyze(resonator_fit_analysis())
candidate = analysis.candidate_config()
accepted = lab.config.accept(analysis)
print(analysis.id)
```

Use `run.analysis(...).save()` only for an exploratory notebook analysis assembled
directly rather than through a reusable analysis step. Both paths return the same
`PublishedAnalysis` handle used by `run.published_analysis(...)`, so immediate and
historical code read tables, figures, derived data, proposals, and candidate
configuration through one durable interface.
Use `fact(...)` for a small typed conclusion and `artifact(...)` for an exact
file or byte sequence produced by the analysis. Both receive stable
analysis-local IDs; artifacts are stored as content-addressed run entries owned
by the analysis publication rather than in an external directory convention.

Published output IDs remain the read boundary after the authoring process exits:

```python
published = run.published_analysis("fit-review")
resonance = published.fact("resonance")
fits = published.dataset("fits")
report = published.artifact("fit-report").text()
table_preview = published.table("fit-table").preview
```

The selector may be an exact analysis record ID or a logical analysis key. A
logical key selects its latest immutable publication; output access rejects a
kind mismatch instead of returning untyped record JSON. Saving identical
content under the same key is idempotent. Changed content appends an automatic
`r2`, `r3`, and so on; the revision also owns distinct datasets, artifacts, and
parameter proposals, so earlier publications remain readable without the user
supplying version numbers.

Analysis trace accepts named inputs. Each dataset input records its durable
target, content hash, and codec; JSON-safe inline inputs are embedded with their
own content hash. Merely reading `context.measurements()` also makes that dataset
an analysis input, so ordinary Python inspection does not require a matching
manual `.input(...)` call. Registered custom output codecs require an encoder;
the execution records the encoder's content identity rather than pretending the
generic Python encoding used that codec.

The analysis-level input reference itself retains the measurement dataset's
content hash and codec, whether or not a trace is used. For completed runs that
immutable dataset hash is the snapshot boundary. Compute execution is an
experiment-program concept; an analysis trace only adds optional named binding
and implementation evidence to the same snapshot identity.

`AnalysisTable.from_rows(...)` remains available for dynamic schemas. The
durable models enforce finite, GUI-safe scalar, derived-data, and point budgets.
The run view renders tables and SVG figures while retaining declared analysis
inputs and optional content-addressed executions as provenance; proposal outputs
remain typed references to their separately persisted proposal records.
