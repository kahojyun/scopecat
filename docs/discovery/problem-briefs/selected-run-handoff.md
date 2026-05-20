# Selected Run Handoff

## Status

Evidence-backed problem brief.

Related spike summary:
[`../selected-run-handoff-spike-summary.md`](../selected-run-handoff-spike-summary.md).

## User-Facing Failure

Selected measurement records and their necessary context are hard to move and
reopen without losing source identity, silently transforming selected source
data, or silently trusting incomplete artifacts. The first workflow is selected
measurement export with optional linked context, not migration of an entire
analysis workspace.

## Observed Sample Evidence

- Curated analysis folders contain CSV/INI inputs, NPY/NPZ summaries, notebooks,
  helper code, rendered PDFs, workbooks, and decks.
- Notebooks select run IDs, external paths, derived arrays, and output
  destinations; some contain mutation-capable parameter or registry cells.
- Generated record families, mapping dictionaries, correction branches, QPT/QST
  expansion, selected IDs, and missing-context signs appear in static research
  notes.
- Data lookup often relies on dataset IDs, directories, local/shared paths,
  filename conventions, or helper code.

## Project-Owner Clarification

- Pre-analysis handoff should stay narrow: selected useful data plus enough
  source identity and missing-context warnings.
- Analysis and report outputs should be linked later, not turn the first
  handoff path into a report generator.
- Same-station access is a constraint on record identity and handoff, not a
  standalone LAN browser by default.
- Handoff should be an export/transfer acceptability test: if Scopecat records
  experiment data and context, selected data and related files should be
  movable to later analysis with recoverable source identity and visible gaps.
- Trustworthy export does not mean a full integrity contract yet. It means
  selected source data is not silently compressed, converted, filtered, or
  replaced by a derived copy without explicit user choice.
- Related-but-not-exported runs should not appear in default selected-data
  export. They may become optional context later only when a group, tag, or
  user note gives them explicit meaning.
- The default selectable export unit should be a measurement or experiment
  record, close to the LabRAD/Labber dataset mental model. Multi-select export
  means exporting multiple selected measurement records, not traversing every
  analysis relation.
- Attachments and artifacts may be linked to measurements, including
  many-to-many links, but those links should be optional declared metadata.
  Inclusion of linked artifacts or source measurements is a later UX policy;
  Scopecat should not silently infer or export a downstream analysis DAG.
- Export/import UX should eventually support quick preview on both sides:
  the exporting user previews measurements before choosing what to export, and
  the importing user previews measurements before accepting or organizing the
  imported package. This preview is for orientation, selection, and confirmation;
  it is not scientific validation, report generation, or a requirement to bundle
  rendered plots.

## Derived Hypotheses

- Ask whether handoff needs separate pre-analysis, analysis, claim/report, or
  recovery/status outputs.
- Stable opaque record IDs, legacy source refs, machine-specific locations, and
  optional shared-storage refs may be enough before central storage or sync.
- Existing NAS or shared-folder locations may support handoff output
  discovery, indexing, validation, or openability checks without making
  Scopecat the owner of central storage or sync.
- Selection rationale should become first-class for the selected run. Anomaly
  notes and missing derived inputs may be carried as notes without promoting
  nearby notebook residue into explicit user decisions.
- Handoff output should carry enough measurement context for collaborators to
  understand what could be shown in a group-meeting figure: experiment label,
  target, measured columns, units, relevant setup or parameter context, and
  candidate plot axes, while still marking missing fit results, calibration
  notes, uncertainty, or scientific validation.
- Early preview should prefer declared measurement roles over inferred schema:
  validate declared column names against source headers first, carry roles and
  units as declared metadata, and treat semantic validation, inference, and
  complex scan-shape support as later validation questions.
- Preview-ready metadata should remain available to future export and import
  GUI flows, but the first validation boundary is still selected source data,
  metadata, and warnings rather than rendered plots or analysis outputs.
- Multi-measurement export should be validated separately from analysis
  lineage. The first question is whether users can export selected measurement
  records with their primary data, metadata, and attachments; optional artifact
  links can be shown without claiming full provenance.

## Out Of Scope For This Brief

- Full report generation, publication workflow, automatic reanalysis, claim
  correctness scoring, central services, remote execution, mandatory shared
  storage, and multi-user sync services.
- Final export/import GUI workflow, rendered preview UI, and plot rendering.
- Treating folder names such as `old`, `backup`, or `copy` as proof of status.
- Including related-but-not-exported runs in a default handoff unless a group,
  tag, or user note gives them explicit meaning.
- Automatically traversing or reconstructing an analysis DAG from notebooks,
  filenames, adjacent IDs, folders, or derived outputs.
- Final checksum, archive, package-integrity, or export-format contracts.

## Possible Validation Questions

- Can selected-run handoff outputs preserve source identity, companion files,
  missing-context warnings, no-silent-transform expectations, figure-readiness
  context, and portable openability better than manual copy workflows?
- Can users multi-select measurement records and export their primary data,
  metadata, and attachments without manually reasoning through every file
  relation?
- Can Scopecat discover, index, or validate selected handoff outputs on
  existing shared storage without becoming a central storage service?
- When do downstream analysis/report links become valuable enough to validate
  as their own question rather than as handoff detail?
