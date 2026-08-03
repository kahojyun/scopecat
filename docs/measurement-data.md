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

Use explicit rows when points are correlated, sparse, adaptive, duplicated, or
otherwise do not form a rectangular product:

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

Domain-program result axes remain fixed-size. Variable-length axes currently
belong to typed instrument acquisitions, where every returned value is checked
before entering the measurement stream.

## Read and slice measurements in notebooks

`run.data().measurements()` returns the labeled analysis facade:

```python
data = run.data().measurements()

data.coords                    # coordinate variables by id
data.data_vars                 # observable variables by id
data["readout.dc_bias"].values

near_zero = data.sel(
    **{"readout.dc_bias": sc.Quantity(0.0, "V")},
    method="nearest",
)
subset = data.isel(point=slice(0, 20))
valid = data.where(data["temperature"].is_available())
groups = data.groupby("amplification")
```

Exact selection retains every matching row, including duplicate point-cloud
coordinates. Numeric coordinate selection accepts unit-aware quantities and an
optional nearest tolerance. Boolean masks compose with `&`, `|`, and `~`.

The same view connects to common analysis ecosystems:

Install the `scopecat[data]` extra to enable these optional adapters.

```python
xds = data.to_xarray()
table = data.to_arrow()
frame = data.to_pandas()                  # one row per experiment point
long_frame = data.to_pandas(layout="long")
```

Complex values remain complex in Xarray and pandas and become explicit
`{real, imag}` structs in Arrow. Unavailable values remain null or missing and
gain a companion `__unavailable_reason` variable or column. The durable Pydantic
records remain available through `data.raw` when low-level inspection is
actually needed.

## Let the GUI use experiment knowledge

The complete planned schema travels with live measurement appends, so plotting
does not wait for a run to finish and does not guess solely from JSON values.
Automatic plots use:

- coordinate versus observable roles and primary-variable ordering;
- dimensions and recording groups to pair trace coordinates with samples;
- labels and units for axes and table columns;
- data type information, with complex magnitude stated explicitly; and
- point-domain layout, using scatter for point clouds and a line only for a
  monotonic grid coordinate.

Point-scalar observables become coordinate plots; point-local rank-one arrays
become trace series. Shapes that do not have a safe automatic visual remain in
the typed table, with raw records available as a secondary expandable view.
This keeps automatic plotting useful without pretending that every tensor has
one obvious chart.
