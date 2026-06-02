# Handoff Package Preview Shape View Validation Result

## Status

Implementation candidate validated.

Document role: historical discovery validation result. It records what this
slice earned and what it did not establish. Current handoff implementation
boundaries are owned by
[`handoff.md`](../../../../engineering/prototype-boundaries/handoff.md);
do not update this result to mirror live API or route changes.

This result validates a narrow read-only consumer of declared preview
plot/view metadata. It is not accepted Scopecat architecture, a final
data-shape schema, storage mapping, dataframe or array API, plotting layer,
importer, GUI contract, or scientific validation model.

## Implementation Candidate

Implementation candidate:
[`../../implementation_candidates/handoff_package_preview_shape_view/`](../../../../../implementation_candidates/handoff_package_preview_shape_view)

Direct tests:
[`../../tests/test_handoff_package_preview_shape_view_candidate.py`](../../../../../tests/test_handoff_package_preview_shape_view_candidate.py)

Fixture inputs:

- [`../../tests/fixtures/handoff_package_opener/basic_package/package/handoff-package-legacy-rabi-001/`](../../../../../tests/fixtures/handoff_package_opener/basic_package/package/handoff-package-legacy-rabi-001)
- [`../../tests/fixtures/scan_data_shapes/`](../../../../../tests/fixtures/scan_data_shapes)

## What This Earned

The candidate shows that the handoff package read-only route can preserve
declared preview metadata and expose a reader-facing preview projection without
importing the scan-shape spike as a final product schema:

- the opener carried manifest-declared `data_shape` into opened
  `declared_preview` facts;
- the read view exposes copy-safe declared preview shape and plot-candidate
  facts;
- the preview projection normalizes declared preview affordance, axis order,
  column metadata, and plot-candidate bindings;
- the package route was proven for the existing one-dimensional
  declared-table package fixture;
- richer scan/data-shape fixtures provide input pressure for preview
  affordances such as heatmap, ragged line-family, trace-family,
  component-pair scatter, and complex component-pair scatter;
- unsupported preview affordances, declared plot-kind mismatches, and
  incomplete or metadata-inconsistent plot bindings become review findings
  instead of runtime inference or plotting failures.

## Boundary

This candidate deliberately consumes declared metadata only. It does not:

- infer shape from CSV headers, source filenames, notebooks, sidecar
  conventions, trace files, or binary containers;
- open trace files or validate trace row contents;
- validate fixed-vector cell values, complex components, or scientific
  correctness;
- render plots, fit data, align traces, resample traces, or build GUI widgets;
- define final package manifest schema, storage schema, dataframe API, array
  API, xarray-like semantics, or query behavior;
- accept/import packages or mutate storage.

The measurement record owns declared acquisition or scan semantics. The primary
data item owns physical table/file facts. This slice owns only the declared
reader projection that binds those facts into preview affordances.

The scan/data-shape fixtures remain concept evidence. Only the
one-dimensional package fixture was opened through the package route; richer
fixture cases are pressure examples for the preview projection normalizer.

## Result

At this checkpoint, the receiving-side package route had a first declared
preview projection consumer. Future SDK or GUI slices can ask whether declared
metadata offers a preview table, heatmap, ragged line-family, trace-family,
component-pair, or complex component-pair candidate without inferring shape
from data files.
