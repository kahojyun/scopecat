# Selected Run Handoff Spike Summary

## Status

Validation summary for the selected-run handoff and preview spikes.

This is not product scope, not an ADR, not a data schema, not a package/export
format, and not a plotting API.

Decision-ready consolidation:
[`selected-measurement-export-decision-summary.md`](selected-measurement-export-decision-summary.md).

## Inputs

- [`problem-briefs/selected-run-handoff.md`](problem-briefs/selected-run-handoff.md)
- [`adoption-hypotheses.md`](adoption-hypotheses.md)
- `spikes/selected_run_handoff/`
- `spikes/selected_run_preview/`
- `tests/fixtures/selected_run_handoff/minimal/`
- `tests/fixtures/selected_run_handoff/multi_measurement_export/`

## What The Spikes Showed

The selected-run handoff spike showed that a tiny public-safe export fixture can
produce a reviewer-facing handoff summary with:

- selected source identity and export provenance;
- present and missing file checks;
- source data, copied parameter context, companion artifacts, and derived
  artifacts kept distinct;
- a source transform policy for selected source data;
- missing-context warnings and explicit scientific-validation boundary notes;
- figure-readiness context without turning the output into a report.

The selected-run preview spike showed that declared column names and roles are
enough to produce a small plot-spec-ready display preview for one 1D CSV case:

- declared sweep axis: `drive_amp`;
- declared measured responses: `iq_i`, `iq_q`;
- declared held condition: `bias_v`;
- declared column-name validation against the CSV header;
- a small preview table;
- multiple plot candidates from the same selected source table;
- a caption stub that remains explicit about missing fit, uncertainty, and
  scientific validation.

## Earned Working Direction

These spikes support keeping selected-run export/handoff as a near-term
validation direction.

The useful shape is a bounded selected-data export/handoff output: only the
selected data and needed context are exported by default. Related but unselected
runs should remain outside the default handoff unless a group, tag, or user note
gives them explicit meaning.

The first selectable export unit should remain a measurement/experiment record.
Multi-select export means selecting multiple measurement records and exporting
their default bundles, not treating every file, artifact, and derived result as
peers in an automatically traversed analysis graph. Attachments and artifacts
may have declared links, including many-to-many links, but inclusion policy is a
later UX question.

For preview, declared measurement roles remain the current candidate first path.
The spike validates declared column names against the source header and carries
roles/units as declared metadata. It does not validate role semantics, unit
correctness, held-condition constancy, numeric suitability, or scientific
validity.

Future export/import UX should be able to use the same declared metadata for
quick preview in both directions: exporters preview candidate measurements
before selecting a package, and importers preview incoming measurements before
accepting or organizing them. That expectation does not make rendered plots,
GUI design, report generation, or user/domain scientific conclusions part of
this spike.

## Not Earned

These spikes do not earn:

- final manifest, summary, or preview schema;
- package/export format or checksum/integrity contract;
- complete reader/export API;
- central storage, sync, or shared-storage indexing;
- notebook parsing or automatic discovery from real lab folders;
- automatic analysis-DAG inference or relation traversal;
- artifact/source inclusion policy for many-to-many links;
- final export/import GUI workflow;
- scan declaration design beyond one 1D CSV fixture;
- automatic schema inference;
- plotting or rendered preview output;
- 2D scans, ragged scans, traces, complex arrays, NPZ/HDF5, or backend readers;
- report generation or reanalysis;
- fit quality, uncertainty, user/domain scientific conclusions, or
  reproducibility claims.

## Validation Result

Domain review passed for the bounded export/transfer scope: selected
measurement records can be represented with recoverable source identity, primary
data, labels, copied context, included/optional/missing linked files, and clear
trust boundaries.

The multi-measurement fixture makes the current export-unit boundary explicit:
multi-select means selected measurements, optional linked artifacts are not
silently included, and Scopecat does not infer or traverse an analysis DAG.

This result is superseded by the repo-local selected measurement export
consolidation in
[`selected-measurement-export-decision-summary.md`](selected-measurement-export-decision-summary.md).

## Open Questions

- Is the generated preview enough to support first-pass slicing or rough figure
  planning without rendered plots?
- What minimal preview should export and import GUIs show before selection or
  acceptance?
- Are declared roles acceptable as the first preview path, or does the first
  real workflow need adapter-generated declarations?
- Should scan declaration become the next validation slice before any durable
  recording API or data schema is designed?
- When should optional linked-artifact inclusion UX be validated?

## Historical Next Fork

This was the next fork at the time of the spike summary. It has since been
completed and superseded by the repo-local selected measurement export
consolidation and validation result.

The historical fork was:

- implement preview-ready selected measurement export as the candidate slice;
- keep exported records source/metadata-first;
- include declared preview-ready metadata, but do not build the full export GUI,
  import GUI, rendered plotting, package integrity model, or final storage
  schema in the same step.

For the current position, read:

- [`selected-measurement-export-decision-summary.md`](selected-measurement-export-decision-summary.md)
- [`preview-ready-selected-measurement-export-validation-result.md`](preview-ready-selected-measurement-export-validation-result.md)

Only fork back into discovery if a specific unresolved question blocks a future
plan:

- artifact inclusion UX for many-to-many links;
- the minimal preview needed before export selection or import acceptance;
- a harder scan shape that is truly blocking the first implementation slice;
- a stronger package integrity requirement.

Avoid adding plotting dependencies or broad scan support until one of those
reviews makes it the next blocking question.
