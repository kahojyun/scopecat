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
- declared sidecar metadata for weakly labeled table columns;
- header, row-count, coordinate-coverage, group-coverage, and mapping sanity checks;
- plot-candidate descriptions only.

It is not a storage schema, dataframe API, legacy importer, plotting layer,
schema inference engine, or scientific validation tool. Harder scan shapes such
as trace-per-point data, array-valued responses, and backend-specific binary
containers remain deferred shape risks.
