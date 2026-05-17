# Measurement Records And Sidecars

## Status

Evidence-backed pain packet. Not a storage schema, reader API, export format,
GUI contract, or source-relation contract.

## User-Facing Failure

Measurement data, sidecars, metadata, and derived artifacts are split across
Data Vault-style records, CSV exports, NPZ/JSON sidecars, generated files, and
analysis bundles. Users need to know what is primary measurement data, what is
context, what is an attachment, and what remains ambiguous.

## Observed Sample Evidence

- Data Vault/dataframe-like recording has names, paths, independent/dependent
  columns, units, metadata, lazy creation, and row capture.
- Scan code records axes, dependent values, start/stop metadata, CSV exports,
  generated sidecars, and disabled or bypassed recording paths.
- Run-adjacent parameter snapshots, per-sequence NPZ files, JSON metadata,
  derived arrays, notebooks, PDFs, workbooks, and decks are visible.
- Source relations are often implicit through filenames, directories, notebook
  code, run IDs, or sidecar adjacency.

## Project-Owner Clarification

- Near-raw sidecars are often old-system workarounds caused by Data Vault
  limitations, not the desired future shape.
- Future primary measurement data should likely be Scopecat-managed enough to
  support plotting and inspection.
- Cross-run analysis outputs may remain cataloged attachments linked to source
  evidence rather than parsed primary records.

## Derived Hypotheses

- Separate current substrate from desired ownership: Data Vault/table plus
  sidecar workaround versus future primary measurement record.
- Attachment handling should preserve relation uncertainty and avoid rerunning
  notebooks or parsing arbitrary binary payloads.
- Reference cases may use tiny CSV/JSON placeholders, but should mark columns,
  shape, IDs, and scientific values as synthetic.

## Premature / Do Not Promote Yet

- Final table format, Arrow/storage/API choice, canonical record ID model,
  `source_system`, batch/task relation, final source-relation schema, or GUI
  contract.
- Treating sidecar copying as the recommended future workflow.

## Possible Validation Questions

- Can a review view distinguish primary measurement data, old-system sidecars,
  context snapshots, and derived attachments without defining the final storage
  model?
- Which ordinary measurement shapes must be present before the data model is
  credible: IQ, shots, traces, VNA-like records, arrays, or only scalar tables?
