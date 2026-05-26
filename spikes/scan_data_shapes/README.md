# Scan Data Shape Generator Spike

This is a tiny validation spike for declared scan data-shape fixtures.

It reads a fixture directory containing `shape-input.json` plus its referenced
CSV source table and regenerates the expected reviewer surfaces:

- `expected-shape-summary.json`
- `expected-shape-review.md`

The expected JSON files are `internal_validation_summary` artifacts. The
expected Markdown files are `review_summary` artifacts. Neither is a portable
export/package artifact or public report.

Current scope is deliberately narrow:

- declared 2D rectangular grid table;
- declared ragged/adaptive table with variable inner-axis coverage;
- observed-only ragged/adaptive table when expected group counts are unknown;
- declared trace-per-point table with fixture-local trace CSV references;
- declared fixed-vector response table for compact per-row single-shot values;
- declared complex fixed-vector response table for cartesian logical complex
  values;
- declared sidecar metadata for weakly labeled table columns;
- header, row-count, coordinate-coverage, group-coverage, trace-reference,
  fixed-vector, complex logical value, and mapping sanity checks;
- plot-candidate descriptions only.

It is not a storage schema, dataframe API, legacy importer, plotting layer,
schema inference engine, general ndarray API, complex primitive storage model,
transform engine, or scientific validation tool. Harder scan shapes such as
complex trace responses, matrix heatmap analysis previews, and backend-specific
binary containers remain deferred shape risks.

## Validation Assumptions

`shape-input.json` is repository-safe discovery fixture metadata, not an
untrusted public import API. The generator should still avoid hard crashes for
malformed values in fields it explicitly consumes for the supported shape
families.

The spike validates only the declared metadata and source facts needed for the
reviewer-facing summary: declared columns, axis metadata, source-table
coordinates, trace references, trace columns, and fixed-vector cells. It does
not perform full JSON Schema validation, arbitrary unused-field validation,
generic ndarray validation, scientific correctness checks, broad free-text
redaction, or public API compatibility checks.

When fixture metadata is malformed inside this stated scope, the expected
behavior is a structured failed summary with no plot candidates for the invalid
shape. When metadata outside this stated scope is malformed, that is a future
contract decision rather than a requirement for this spike.
