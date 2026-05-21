# Preview-Ready Selected Measurement Export Plan

## Status

Implementation-planning draft.

This is not an ADR, product contract, final schema, package format, GUI design,
reader/import API, or plotting API. It defines the smallest implementation
slice that follows from
[`selected-measurement-export-decision-summary.md`](selected-measurement-export-decision-summary.md).

Concrete implementation planning is tracked separately in
[`preview-ready-selected-measurement-export-implementation-plan.md`](preview-ready-selected-measurement-export-implementation-plan.md).

## Goal

Plan and pressure-test a source/metadata-first selected measurement export
slice that is preview-ready.

Preview-ready means exported measurement records carry enough declared metadata
to avoid blocking later preview surfaces on both sides of a transfer:

- export-side preview helps users choose measurements before packaging;
- import-side preview helps users confirm incoming measurements before
  accepting or organizing them;
- preview is orientation and selection support, not rendered plotting,
  analysis, fit validation, uncertainty, reproducibility, or scientific
  validation.

## Minimum Input Shape

The first implementation slice should require explicit measurement records with
enough source identity to export even when preview metadata is incomplete:

- stable measurement identifier;
- human-facing label;
- target or subject label when known;
- source provenance reference;
- primary data locator/reference, whose first fixture form is a
  package-relative `source_file`;
- source authority, either measurement-level or carried by the included
  `primary_data` bundle item;
- optional linked files with kind, label, path, inclusion status, relation, and
  relation authority;
- warnings for missing, local-only, unverified, or ambiguous context.

Preview-ready fixture cases should additionally include:

- declared data shape;
- declared column or field roles;
- labels and units for declared roles when available;
- optional held/static conditions;

Missing preview metadata should degrade the preview surface and produce an
explicit warning. It should not make a selected measurement unexportable unless
the source identity or primary data reference is missing.

Required export fields should appear in fixtures and tests. Helpers should not
silently supply required input.

## Minimum Fixture Output

The first export/review output should show:

- selected measurement IDs and labels;
- selected source identity and export provenance;
- default included primary data and metadata;
- user-included optional linked files, when present;
- visible but excluded optional linked files, when present;
- missing or local-only linked files;
- non-recursive traversal policy;
- source transform policy for selected source data;
- declared preview metadata: shape, roles, labels, units, and candidate axes or
  responses where available;
- preview-unavailable or preview-incomplete warnings when declared metadata is
  missing;
- reviewer boundary notes that preview is not rendered plotting, analysis
  lineage, or scientific validation.

The output may include plot-candidate metadata, but should not include rendered
plots as part of this slice.

## Reference Semantics

The fixture uses filesystem-looking strings because it materializes public-safe
test files. Those strings should not be read as the final Scopecat storage
model.

Use these meanings for the first slice:

- `local_path`: original machine-local or lab-local location. This is
  non-portable, may be redaction-sensitive, and should be treated as an
  external reference with warnings.
- `export_source`: recoverable source identity for where the selected data came
  from. It is provenance, not necessarily the current read location.
- `source_file`: package-relative locator for the selected primary data copy in
  these fixtures. It is a convenience fixture form of the primary data
  locator/reference, not the final canonical storage identity.
- fixture `path` fields: package-relative or fixture-relative materialized
  files used for openability checks and expected output tests.
- `primary_data` bundle item: the included materialized primary-data item. In
  the first fixture its `path` matches `source_file`, and its `authority`
  supplies the selected source authority.
- managed Scopecat primary data: future internal data may be addressed by
  record IDs, artifact IDs, storage object references, or backend-specific
  handles instead of user-facing filesystem paths.

Recording only external file locations is a plausible transition or
external reference mode, but it does not provide the same durability as managed
Scopecat data. In that mode Scopecat can label, warn, check openability, and
preserve source identity, but users can still be affected if external files are
moved, deleted, renamed, or only available on one machine.

The first acceptance fixture validates package-relative materialized export
files, not external-reference-only export. External reference mode remains
deferred and would need weaker openability/durability expectations.

The first slice should avoid hard-coding `path` as the durable identity model.
It may use package-relative paths in fixtures and export reviews while keeping
the final storage layout, object-ID scheme, and external-reference policy
deferred.

## First Implementation Acceptance Tests

Start with fixture-level tests before product integration. The first executable
acceptance fixture is
`tests/fixtures/selected_run_handoff/preview_ready_measurement_export/`. It
integrates multi-measurement export with one selected measurement that has
declared preview metadata and one selected measurement whose preview metadata is
incomplete or unavailable.

The fixture now has a tiny generator at
`spikes/selected_measurement_export/`. Generator tests compare the generated
summary and Markdown review exactly against the expected fixture outputs.

- one selected measurement exports its default source/metadata bundle;
- multiple selected measurements remain the explicit export set;
- optional linked files are reported with declared inclusion status;
- user-included optional linked files are distinct from visible-but-excluded
  optional linked files;
- missing linked files and local-only source references are reported;
- linked files carry human-facing labels as well as paths;
- traversal remains non-recursive;
- declared preview metadata is present for supported preview-ready shapes;
- incomplete preview metadata produces an explicit degraded-preview warning
  rather than blocking export;
- preview metadata is generated from declared roles and shapes, not inferred
  from notebooks, filenames, or weak headers;
- selected source data is marked against silent compression, conversion,
  filtering, or replacement by derived copies;
- reviewer notes say what is not validated: rendered plot, fit quality,
  uncertainty, user/domain scientific conclusions, reproducibility, and full
  analysis lineage.

## Fixture Pressure Coverage

Existing fixtures should be treated as source concepts, not as the complete
acceptance contract:

- `selected_run_handoff/minimal` covers single-run source identity,
  no-silent-transform posture, figure-readiness context, and missing files;
- `selected_run_handoff/multi_measurement_export` covers selected measurements,
  labels, optional linked context, and non-recursive traversal;
- `scan_data_shapes/*` covers declared preview metadata for 2D grid and
  sidecar-declared weak-table cases.

The integrated `preview_ready_measurement_export` fixture is the first
acceptance target for implementation planning. It prevents an implementation
from satisfying the older multi-measurement export concept while still omitting
preview-readiness behavior.

The selected measurement export generator is the first executable check for
that target. It should remain bounded to static fixture metadata and should not
grow real package writing, GUI preview, importer, plotting, storage, or
automatic schema-inference behavior.

For the next code-facing slice, use
[`preview-ready-selected-measurement-export-implementation-plan.md`](preview-ready-selected-measurement-export-implementation-plan.md)
to keep production-shaped work limited to a pure selected measurement export
summary builder. Any Markdown review rendering should stay fixture/test
reviewer support before considering package writing, GUI, or import behavior.

## Implementation Boundary

Do not include these in the first slice:

- final package/archive format;
- checksum or package integrity contract beyond the no-silent-transform
  expectation;
- final measurement, artifact, attachment, relation, or data-shape schema;
- export GUI;
- import GUI;
- rendered plot preview;
- interactive slicing;
- dataframe dependency choice;
- real LabRAD, Labber, notebook, sidecar, HDF5, NPZ, or arbitrary file readers;
- automatic schema inference;
- automatic analysis-DAG inference or relation traversal;
- artifact inclusion UX for many-to-many links;
- ragged/adaptive scans, trace-per-point data, array-valued responses, or
  backend-specific binary containers.

## Fixtures To Start From

Use existing public-safe fixture concepts as the first implementation pressure
tests:

- `tests/fixtures/selected_run_handoff/minimal/`
- `tests/fixtures/selected_run_handoff/multi_measurement_export/`
- `tests/fixtures/selected_run_handoff/preview_ready_measurement_export/`
- `tests/fixtures/scan_data_shapes/2d_grid_table/`
- `tests/fixtures/scan_data_shapes/sidecar_declared_table/`

The likely first implementation fixture is
`preview_ready_measurement_export`. The older `minimal` handoff fixture should
remain reference coverage for single-run trust and figure-readiness details, not
the primary implementation target.

The fixtures should stay small and explicit. They should exercise selection,
default inclusion, optional links, missing context, declared preview metadata,
and warning surfaces without becoming broad legacy importer coverage.

## Deferred Decisions

These should remain separate decisions unless they block the first slice:

- exact export/import GUI flow;
- minimal preview UI content before export selection or import acceptance;
- default include policy for attachments versus artifacts;
- artifact naming and labeling UX;
- many-to-many relation model;
- package/archive format;
- checksum or integrity guarantee;
- final storage schema;
- importer strategy for existing lab systems;
- support for harder scan shapes.

## Done For This Planning Stage

This plan is sufficient when it lets an implementation task be written with:

- a clear fixture set;
- required input fields;
- expected output fields;
- explicit non-goals;
- first acceptance tests;
- deferred UX, schema, and integrity decisions.
