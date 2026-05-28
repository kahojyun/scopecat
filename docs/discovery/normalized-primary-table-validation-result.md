# Normalized Primary Table Validation Result

## Status

Implementation candidate validated.

Artifact posture: `internal_validation_summary`. This document and the
expected fixture are repository review artifacts. They are not portable,
public, export, or package output.

## Validation Question

Can Scopecat validate the smallest table-read contract for already-normalized
primary CSV data without making it an adapter, storage, package, dataframe, or
schema-inference slice?

## Result

Yes, for the validated fixture.

The candidate validates `csv_table` bytes supplied by the caller and returns
local table facts:

- UTF-8 CSV decoding;
- one non-empty header row;
- unique, non-blank column names;
- rectangular string-valued rows, including quoted multiline cell values;
- declared preview-column names and supported column roles against observed
  columns;
- complete string-valued table rows;
- preview rows limited to the declared preview columns;
- row-count mismatch as a review finding.

This is a data-level table read contract for Scopecat-readable normalized
primary data. It is not a legacy parser and does not prove that arbitrary
external files are previewable.

## Boundary

The candidate starts from already-provided bytes. It does not open files,
observe filesystem paths, compare digest or size facts, mutate storage,
package data, accept imports, or decide adapter handoff transport.

Column names remain table keys and may be user-facing strings. They are not
public-safe identifiers by default. Empty, blank, or duplicate column names are
rejected because they cannot form stable table keys. Declared column roles are
contract values and must use the current supported role vocabulary.

Declared preview columns are a binding contract over the observed table. The
table may contain additional columns, which remain available as table columns
but are not included in preview rows unless declared.

All emitted values remain strings. The candidate does not infer scalar types,
units, dataframe dtypes, scan shape, plot series, or GUI behavior.

## Validated Behavior

- `summarize_normalized_csv_table()` returns `normalized_table_ready` for the
  repository fixture.
- Extra table columns are preserved as undeclared table columns.
- Declared row-count mismatch returns `normalized_table_review_needed` with a
  review finding.
- Duplicate headers, blank headers, missing declared columns, ragged rows, and
  non-UTF-8 bytes are rejected before table facts are emitted.

## Decisions Not Earned

- final storage table format or storage schema;
- adapter transport, adapter API, or legacy-source parser;
- package format, package integrity, or file observation;
- schema inference, scalar-type inference, scan-shape inference, or dataframe
  dtype inference;
- plotting, fitting, GUI behavior, or public SDK names;
- large-file streaming or query behavior.

## Follow-Up

Use this primitive when another slice needs the same normalized CSV table
semantics. Handoff package opener, storage source observation, adapter output,
and future SDK/GUI work should adopt it only when their route boundary needs
the shared table behavior, not merely because they mention CSV files.
