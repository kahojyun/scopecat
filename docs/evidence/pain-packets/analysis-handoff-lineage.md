# Analysis Handoff And Lineage

## Status

Evidence-backed pain packet. Not a report generator, publication workflow,
central storage plan, remote execution surface, or full ELN/LIMS scope.

## User-Facing Failure

Selected runs, source IDs, required sidecars, notebooks, helper code, derived
arrays, figures, workbooks, and reports are hard to move, reopen, and trace
back to source evidence without losing context or silently trusting incomplete
artifacts.

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

- Split handoff into pre-analysis package, analysis packet, claim/report packet,
  and recovery/status packet.
- Stable opaque record IDs, legacy source refs, machine-specific locations, and
  optional shared-storage refs may be enough before central storage or sync.
- Selection rationale should become first-class: active ID, rejected
  alternatives, anomaly notes, and missing derived inputs.

## Premature / Do Not Promote Yet

- Full report generation, publication workflow, automatic reanalysis, claim
  correctness scoring, central server, generated indexes, background indexer,
  live sync, remote execution, or mandatory shared storage.
- Treating folder names such as `old`, `backup`, or `copy` as proof of status.

## Possible Validation Questions

- Can selected-run packages preserve source identity, sidecars, missing-context
  warnings, and portable openability better than manual copy workflows?
- When does analysis/report lineage become valuable enough to validate as its
  own packet rather than as handoff detail?
