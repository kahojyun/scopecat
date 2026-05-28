# Scan Data Shape Decision Summary

## Status

Decision summary for the current scan/data-shape discovery checkpoint.

This summary closes the current shape-expansion phase. It does not accept a
final product schema, storage backend, plotting implementation, dataframe API,
array API, reader SDK, importer, or public/export report format.

Artifact posture:

- this document is a discovery decision summary;
- it is not a portable export/package artifact or public report;
- it records what current fixture evidence supports and where follow-up work
  should move next.

## Accepted Direction

Scopecat should model measurement data for preview as **declared previewable
data items**, not arbitrary tables, arrays, files, or artifacts.

The key durable direction is:

- shape semantics stay explicit and storage-independent;
- storage backends may use scalar columns, lists, structs, sidecar files, or
  future native capabilities, but storage shape is not the semantic authority;
- preview candidates come from declared roles, axes, units, components,
  completeness facts, and logical value metadata;
- reader convenience views, such as ndarray-shaped views for validated
  fixed-vector columns, may exist without becoming the core data model;
- arbitrary artifacts are stored or referenced by default and are not
  visualized unless materialized into a supported preview model;
- complex values are logical value metadata over declared representations, not
  primitive storage types.

## Validated Shape Families

Current fixture evidence is enough to keep these shape families as candidate
preview models:

- rectangular grid table for complete two-axis scans and heatmap-like preview
  candidates;
- declared ragged/adaptive table when expected group point counts are known;
- observed-only ragged/adaptive table when completed adaptive coverage is known
  but planned group counts are not;
- trace-per-point table that binds outer scan coordinates to fixture-relative
  trace tables;
- fixed-vector response table for compact fixed-shape per-row values such as
  IQ pairs;
- complex fixed-vector response table for cartesian logical complex values and
  declared real, imaginary, magnitude, and phase views;
- sidecar-declared weak table where external metadata provides column meaning.

These families are evidence for model adequacy, not final schema names or
storage layout.

## Explicit Deferrals

The current checkpoint should not expand into:

- generic ndarray or array-valued response support;
- primitive complex storage in the Scopecat table model;
- pandas-like multi-index table semantics;
- xarray-like labeled-array semantics;
- nested dataframe design;
- arbitrary artifact visualization;
- QST/QPT matrix heatmap support;
- complex trace response support;
- backend-specific binary container parsing;
- publication-grade plotting or scientific validity review;
- legacy importer behavior or schema inference.

Any of those may become future slices only when a specific consumer needs them
and the slice can validate one narrow boundary.

## Next Consumer

The next work should stop adding scan/data-shape variants and move toward a
product-facing consumer of declared preview metadata.

The best next candidates are:

- selected-measurement preview compatibility: determine which existing
  selected measurements can produce declared preview candidates and which
  should surface degraded-preview findings;
- handoff package open/read-view consumption: prove that package readers can
  consume declared preview metadata without importing a shared measurement
  schema, dataframe adapter, or plotting stack.

Either route should consume the current shape vocabulary as input pressure
only. It should not promote fixture JSON into a shared product schema unless
repeated consumers demonstrate the same durable contract.

## Related Boundaries

Use these documents with this decision summary:

- [`scan-data-shape-validation-result.md`](scan-data-shape-validation-result.md)
  for fixture evidence and validation scope;
- [`artifact-preview-boundary.md`](../../policies/artifact-preview-boundary.md) for arbitrary
  artifact versus previewable data item behavior;
- [`complex-response-boundary.md`](../../policies/complex-response-boundary.md) for complex
  logical value metadata;
- [`shared-model-extraction-deferral.md`](../../synthesis/shared-model-extraction-deferral.md)
  for why shared product schemas remain deferred.
