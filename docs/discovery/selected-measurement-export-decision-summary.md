# Selected Measurement Export Decision Summary

## Status

Decision-ready discovery summary. Its recommended implementation candidate has
now been validated; use
[`preview-ready-selected-measurement-export-validation-result.md`](preview-ready-selected-measurement-export-validation-result.md)
for the current slice recommendation.

This is not an ADR, product contract, final schema, package format, GUI design,
reader/import API, or plotting API. It summarizes what the earlier validation
earned enough to carry into the preview-ready selected measurement export
implementation-planning conversation.

## Inputs

- [`problem-briefs/selected-run-handoff.md`](problem-briefs/selected-run-handoff.md)
- [`selected-run-handoff-spike-summary.md`](selected-run-handoff-spike-summary.md)
- [`problem-briefs/measurement-record-boundary.md`](problem-briefs/measurement-record-boundary.md)
- `spikes/selected_run_handoff/`
- `spikes/selected_run_preview/`
- `spikes/scan_data_shapes/`
- `tests/fixtures/selected_run_handoff/minimal/`
- `tests/fixtures/selected_run_handoff/multi_measurement_export/`
- `tests/fixtures/selected_run_handoff/preview_ready_measurement_export/`
- `tests/fixtures/selected_run_handoff/storage_transition_export/`
- `tests/fixtures/scan_data_shapes/`

## Earned Candidate

The implementation candidate selected by this summary was preview-ready
selected measurement export.

That means:

- the default selectable export unit is a measurement or experiment record;
- multi-select export means selecting multiple measurement records;
- export carries primary data, basic measurement metadata, recoverable source
  identity, and warnings;
- linked attachments or artifacts may be shown as optional includes, but export
  traversal is non-recursive by default;
- linked artifacts, derived outputs, notebooks, reports, and source
  measurements are not silently pulled into the package;
- declared shape, role, label, and unit metadata should make exported
  measurements preview-ready when that metadata is available;
- missing preview metadata should produce degraded-preview warnings rather than
  blocking export of otherwise valid selected measurements;
- preview readiness supports future export selection and handoff-package
  contents confirmation;
- preview does not mean rendered plots, report generation, fit validation,
  uncertainty, reproducibility, or user/domain scientific conclusions.

## Why This Is Enough For A Next Slice

The current fixtures and spikes cover the main product boundary:

- selected source identity and export provenance can be carried forward;
- selected source data can be marked against silent compression, conversion,
  filtering, or replacement by derived copies;
- primary data, copied parameter context, companion files, optional linked
  artifacts, missing context, and local-only paths can be distinguished;
- fixture paths can stand in for package-relative materialized files without
  making filesystem paths the durable identity model;
- source identity, current references, and package materialization paths can be
  distinguished for managed data and externally referenced data;
- selected measurements can be exported together without treating adjacent IDs
  or rejected alternatives as implicit export members;
- declared metadata can produce simple preview and plot-candidate surfaces
  without inferring schema from notebooks, filenames, or weak CSV headers;
- rectangular 2D grid and sidecar-declared weak-table fixtures are enough to
  keep scan-shape validation moving without committing to broad importer scope.

## Still Not Earned

- Final manifest, package, archive, checksum, or integrity contract.
- Final storage layout, object-ID scheme, or external-reference policy.
- Final measurement, attachment, artifact, relation, or data-shape schema.
- Final export and handoff-package contents GUI workflow.
- Artifact inclusion UX for many-to-many links.
- Automatic analysis-DAG inference, relation traversal, or ownership.
- Real LabRAD, Labber, notebook, sidecar, HDF5, NPZ, or dataframe readers.
- Rendered plot preview, interactive slicing, or plotting dependency choice.
- Ragged/adaptive scans, trace-per-point data, array-valued responses, or
  backend-specific binary containers.
- Unit semantic validation, fit quality, uncertainty, user/domain scientific
  conclusions, or reproducibility.

## Later Questions

- What minimal preview surface should export show before users select
  measurements?
- What minimal handoff or export-package contents preview should receiving
  users see before they accept, open, or organize a Scopecat-created package?
- What minimal incoming-record preview should external import candidates show
  before users accept or organize them?
- Which linked files should be default includes versus optional includes?
- How should users name or label attachments and artifacts without excessive
  friction?
- What integrity guarantee is needed beyond the current no-silent-transform
  expectation?
- When should Scopecat ingest/manage primary data versus merely record an
  external reference?
- When a harder scan shape becomes blocking, what declared shape model is needed
  before implementation?

## Historical Recommendation

This summary was used as the planning boundary for a small implementation
slice:

preview-ready selected measurement export.

Planning draft:
[`preview-ready-selected-measurement-export-plan.md`](preview-ready-selected-measurement-export-plan.md).

Implementation-candidate validation:
[`preview-ready-selected-measurement-export-validation-result.md`](preview-ready-selected-measurement-export-validation-result.md).

First acceptance fixture:
`tests/fixtures/selected_run_handoff/preview_ready_measurement_export/`.

Tiny generator:
`spikes/selected_measurement_export/`.

That implementation-candidate validation is now complete. The current
recommendation is to pause this slice at the structured-summary boundary unless
another concrete task needs it; see
[`preview-ready-selected-measurement-export-validation-result.md`](preview-ready-selected-measurement-export-validation-result.md).
