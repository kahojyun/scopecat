# Artifact Preview Boundary

## Status

Discovery boundary accepted for current validation slices.

This note defines how Scopecat should separate arbitrary artifacts from
previewable data items while scan/data-shape work remains storage-independent.
It does not define a final artifact schema, plotting API, dataframe API,
array API, public report format, or storage backend.

## Boundary

Scopecat should not provide default visualization for arbitrary-shaped
artifacts.

The same rule applies to original legacy measurement files. Recording a
reference to a Data Vault, LabRAD, Labber, shared-drive, or old-system file is
not enough to make that file previewable. Plotting or dataframe-like access
requires normalized Scopecat-readable data or an explicitly supported
previewable data item.

An artifact is any stored or referenced result that may have provenance,
metadata, checksums, relation links, and openability facts. By default,
Scopecat can list it, identify it, link it to source measurements, report
review findings, and hand it to an external tool or later explicit consumer.
It should not infer a plot from arbitrary content, nested arrays, binary
containers, file extensions, labels, or analysis names.

A previewable data item is narrower: it declares a Scopecat-understood preview
model with enough semantic metadata for conservative plot candidates. Current
validated examples include rectangular grid tables, ragged/adaptive tables,
trace-per-point tables, sidecar-declared weak tables, and fixed-vector
response tables.

Analysis outputs can become previewable only when materialized into a
supported preview model. For example, a QST or QPT matrix may be stored as an
analysis artifact by default. It should become heatmap-previewable only if a
later slice validates a specific matrix table or matrix heatmap preview model
with declared row axis, column axis, value component, basis, source relation,
and scan coordinate binding.

## Storage Independence

Native `list`, `struct`, Arrow, Parquet, HDF5, Zarr, or similar storage support
does not remove the need for preview metadata. Such formats may store values
more naturally, but they do not by themselves state whether a value is an IQ
pair, trace, image, covariance matrix, QST result, QPT result, or analysis
artifact.

Scopecat can use storage-native lists or structs when useful, but the preview
decision should depend on declared semantics, not storage shape alone.

## Practical Model

Use two separate concepts:

- `artifact`: arbitrary stored or referenced result with provenance and review
  metadata; no default visualization.
- `previewable_data_item`: table, trace, grid, vector, future validated matrix
  model, or other validated model that declares roles, axes, units, components,
  and plot candidate semantics.

This keeps ordinary experiment workflows ergonomic while avoiding a general
pandas, xarray, matplotlib, or ndarray replacement.

## Implications

Current scan/data-shape fixtures support concept validation for previewable
measurement data, not universal artifact visualization.

For single-shot compact responses, a fixed-vector column can be a previewable
data item when each row validates against declared fixed-shape `value_shape`,
`dtype`, and `shape_policy`. A reader may expose a validated ndarray-shaped
view as a convenience, but Scopecat should not treat that as a general
array-column API.

Complex-valued responses are logical value metadata over such previewable data
items, not primitive storage types. The current complex validation is bounded
in [`complex-response-boundary.md`](complex-response-boundary.md).

For traces and waveforms, keep trace-per-point or sidecar trace references
separate from small vector responses.

For QST/QPT or other matrices, defer support until a matrix-specific analysis
preview slice earns the needed semantics. Do not infer heatmaps from arbitrary
2D arrays.

## Decisions Not Earned

This boundary does not accept:

- visualization for arbitrary artifacts;
- generic ndarray or array-valued response support;
- pandas-like multi-index table semantics;
- xarray-like labeled-array semantics;
- publication-grade plotting;
- matrix heatmap support for QST/QPT;
- binary container parsing;
- legacy importer behavior;
- storage-backend selection;
- public/export report behavior.
