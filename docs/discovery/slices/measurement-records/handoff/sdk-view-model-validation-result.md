# Handoff Package SDK View Model Validation Result

## Status

Implementation candidate validated.

This result validates a thin Python-facing view model over the existing
read-only handoff package route. It is not accepted Scopecat architecture, a
final public SDK, a dataframe dependency decision, GUI component model, fitting
engine, writable analysis package, archive format, import flow, or shared
measurement-record schema.

## Implementation Candidate

Implementation candidate:
[`../../implementation_candidates/handoff_package_sdk_view_model/`](../../../../../implementation_candidates/handoff_package_sdk_view_model)

Direct tests:
[`../../tests/test_handoff_package_sdk_view_model_candidate.py`](../../../../../tests/test_handoff_package_sdk_view_model_candidate.py)

Fixture:
[`../../tests/fixtures/handoff_package_opener/basic_package/package/handoff-package-legacy-rabi-001/`](../../../../../tests/fixtures/handoff_package_opener/basic_package/package/handoff-package-legacy-rabi-001)

## What This Earned

The candidate shows that an opened handoff package can be consumed through a
small SDK-like object surface:

- `open_handoff_package_sdk_view(path)` delegates package parsing and file
  opening to the existing read-only opener/read-view route;
- package measurements are accessible by measurement record id or integer
  position;
- primary and preview tables support string column keys, integer column
  positions, rows, records, and optional `to_pandas()`;
- plot specs expose a primary plot plus saved-view style plot ids, axis
  metadata, records, optional `to_pandas()`, and optional `to_numpy()`;
- declared package plot series become XY or IQ scatter specs, and the SDK
  plot-spec object can also represent a long-table heatmap binding without
  rendering, pivoting, or automatic scan-shape inference;
- linked context, findings, and empty analysis/fit extension points remain
  visible for notebook or future GUI use.

Pandas and numpy are optional adapters in this candidate. The repository does
not take either as a hard dependency; adapter methods report a clear missing
dependency when the caller asks for one that is unavailable.

## Boundary

This candidate deliberately stays above the read-only handoff package read
view. It does not:

- define final package or SDK names;
- infer schema, scalar types, units, or dataframe dtypes;
- infer scan/data-shape semantics such as 1D sweeps, 2D grids, ragged scans,
  shot tables, averaging, or missing grid points;
- render plots or define GUI components;
- execute fits, select ROIs, remove outliers, or validate scientific results;
- write analysis artifacts or import analysis results back into storage;
- accept packages, mutate storage, extract archives, or validate signatures.

The package fixture already contains declared `data_shape` metadata, but this
slice only consumes the resulting table and plot bindings. A later contract
slice should decide whether scan/data-shape metadata becomes part of the SDK
surface.

Fit and analysis results are reserved as future read-only extension points.
The current object model returns empty analysis/fit collections so downstream
code can see where those results would attach without committing to an engine
or write-back flow.

## Result

The handoff package route now has a validated notebook-oriented entry surface:
open a package, discover measurements, access primary data as table records or
pandas, and select declared primary/saved plot specs for matplotlib-like or GUI
use. The SDK-side plot shape also covers direct long-table heatmap binding, but
the current package manifest route still supplies declared two-axis plot
series, and this slice does not infer broader scan/data-shape semantics. This
validates the next UX layer without collapsing package reading, GUI rendering,
fitting, storage import, or writable analysis into one model.
