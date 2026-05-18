# Selected Run Handoff

## Status

Evidence-backed problem brief.

## User-Facing Failure

Selected runs, source IDs, required companion files, notebooks, helper code,
derived arrays, figures, workbooks, and reports are hard to move and reopen
without losing context or silently trusting incomplete artifacts.

## Observed Sample Evidence

- Curated analysis folders contain CSV/INI inputs, NPY/NPZ summaries, notebooks,
  helper code, rendered PDFs, workbooks, and decks.
- Notebooks select run IDs, external paths, derived arrays, and output
  destinations; some contain mutation-capable parameter or registry cells.
- Generated record families, mapping dictionaries, correction branches, QPT/QST
  expansion, selected/rejected IDs, and missing-context signs appear in static
  research notes.
- Data lookup often relies on dataset IDs, directories, local/shared paths,
  filename conventions, or helper code.

## Project-Owner Clarification

- Pre-analysis handoff should stay narrow: selected useful data plus enough
  source identity and missing-context warnings.
- Analysis and report outputs should be linked later, not turn the first
  handoff path into a report generator.
- Same-station access is a constraint on record identity and handoff, not a
  standalone LAN browser by default.

## Derived Hypotheses

- Ask whether handoff needs separate pre-analysis, analysis, claim/report, or
  recovery/status packages.
- Stable opaque record IDs, legacy source refs, machine-specific locations, and
  optional shared-storage refs may be enough before central storage or sync.
- Existing NAS or shared-folder locations may support handoff package
  discovery, indexing, validation, or openability checks without making
  Scopecat the owner of central storage or sync.
- Selection rationale should become first-class: active ID, rejected
  alternatives, anomaly notes, and missing derived inputs.

## Out Of Scope For This Brief

- Full report generation, publication workflow, automatic reanalysis, claim
  correctness scoring, central services, remote execution, mandatory shared
  storage, and multi-user sync services.
- Treating folder names such as `old`, `backup`, or `copy` as proof of status.

## Possible Validation Questions

- Can selected-run packages preserve source identity, companion files,
  missing-context warnings, and portable openability better than manual copy
  workflows?
- Can Scopecat discover, index, or validate selected handoff bundles on
  existing shared storage without becoming a central storage service?
- When do downstream analysis/report links become valuable enough to validate
  as their own question rather than as handoff detail?
