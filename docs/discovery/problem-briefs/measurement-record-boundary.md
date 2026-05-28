# Measurement Record Boundary

## Status

Evidence-backed problem brief.

Related validation artifacts:
[`../selected-measurement-export-decision-summary.md`](../slices/measurement-records/selected-measurement-export-decision-summary.md)
and the public-safe `tests/fixtures/scan_data_shapes/` fixtures.

## User-Facing Failure

Measurement data, metadata, companion artifacts, and derived outputs are split
across Data Vault-style records, CSV exports, NPZ/JSON files, generated files,
and analysis bundles. Users need to know what is primary measurement data, what
is context, what is an attachment, and what remains ambiguous.

## Observed Sample Evidence

- Data Vault/dataframe-like recording has names, paths, independent/dependent
  columns, units, metadata, lazy creation, and row capture.
- Scan code records axes, dependent values, start/stop metadata, CSV exports,
  generated companion files, and disabled or bypassed recording paths.
- Run-adjacent parameter snapshots, per-sequence NPZ files, JSON metadata,
  derived arrays, notebooks, PDFs, workbooks, and decks are visible.
- Source relations are often implicit through filenames, directories, notebook
  code, run IDs, or file adjacency.

## Project-Owner Clarification

- Near-raw companion files are often old-system workarounds caused by Data Vault
  limitations, not the desired future shape.
- Fixture paths and legacy file paths should not be treated as the desired
  durable identity model. They represent current substrate pressure or
  package-relative test/export materialization. Managed Scopecat data may later
  use record IDs, artifact IDs, storage object references, or backend handles
  instead of user-facing filesystem paths.
- An external reference mode that records only external file locations may be
  useful for transition or legacy workflows, but it preserves the old risks:
  files can move, disappear, remain machine-local, or depend on user-managed
  directory hygiene.
- Scopecat can record arbitrary legacy source references, but plotting and
  dataframe-like preview should require normalized Scopecat-readable data or a
  supported previewable data item. An original legacy file reference is closer
  to an external source reference or attachment-like artifact until an adapter
  produces normalized primary data.
- Cross-run analysis outputs may remain cataloged as linked artifacts
  associated with source records rather than parsed primary records.
- Legacy CSV/INI/NPY/JSON/workbook combinations should be treated as model
  adequacy stress cases, not as a first-class importer list. The product
  question is whether Scopecat's primary measurement model can carry the
  information those files currently scatter across paths, sidecars, and
  notebooks.

## Derived Hypotheses

- Separate current substrate from desired record boundary: Data Vault/table plus
  companion-file workaround versus future primary measurement record.
- Validate whether future primary measurement data needs to be Scopecat-managed
  enough to support plotting and inspection, without treating that as an
  already-earned storage authority decision.
- Keep source identity, package-relative materialized paths, external
  references, and managed storage identities distinct. Path-shaped fixture
  fields should not imply that Scopecat's future model is path-addressed.
- Linked artifact handling should preserve relation uncertainty and avoid
  rerunning notebooks or parsing arbitrary binary payloads.
- Reference cases may use tiny CSV/JSON placeholders, but should mark columns,
  shape, IDs, and scientific values as synthetic.
- Current shape validation supports declared 1D multi-response tables,
  rectangular 2D grid tables, and weak tables with sidecar-declared metadata as
  enough for product-analysis direction. Ragged scans, trace-per-point data, and
  array-valued measurements remain deferred shape-model risks, not current
  importer requirements.

## Out Of Scope For This Brief

- Final table format, storage/API choice, record ID model, source-relation
  schema, and GUI contract.
- Treating companion-file copying as the recommended future workflow.

## Possible Validation Questions

- Can a review view distinguish primary measurement data, old-system companion
  files, context snapshots, and derived artifacts linked to source records
  without defining the final storage model?
- Which ordinary measurement shapes must be present before the data model is
  credible: IQ, shots, traces, VNA-like records, arrays, or only scalar tables?
- Can a clean declared measurement/data shape represent the important metadata
  now scattered across ad hoc legacy files without making Scopecat support every
  file combination as a durable product format?
