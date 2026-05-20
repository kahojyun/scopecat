# Selected Measurement Export Generator Spike

This is a tiny validation spike for the preview-ready selected measurement
export fixture.

It reads `export-input.json` from
`tests/fixtures/selected_run_handoff/preview_ready_measurement_export/` and
regenerates:

- `expected-export-summary.json`
- `expected-export-review.md`

The command-line entry point is only a fixture-regeneration helper. It rejects
other fixture IDs and should not be treated as a reusable exporter.

Current scope is deliberately narrow:

- selected measurement records as the export unit;
- package-relative fixture paths for materialized test files;
- per-measurement source provenance via `export_source`;
- declared preview metadata when available;
- degraded preview when metadata is missing;
- explicit optional-link inclusion states;
- no-silent-transform posture;
- warnings for degraded or missing states;
- reviewer boundary notes for decisions not earned.

It is not a product exporter, package/archive format, storage schema, importer,
GUI preview, plotting layer, reader API, or scientific validation tool.
