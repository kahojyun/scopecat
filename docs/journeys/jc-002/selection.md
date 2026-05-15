# JC-002 Journey Selection Note

## Status

Historical selection record. The active draft boundary lives in
[`snapshot-boundary.md`](snapshot-boundary.md), and validation detail lives in
[`prototypes/handoff-snapshot.md`](prototypes/handoff-snapshot.md).

## Why This Journey Was Selected

`JC-002` was selected to test internal analysis handoff before broader export,
publication, collaboration, or scientific-comparison scope.

The selected pressure is:

```text
valuable post-run data on a control computer
  -> selected runs plus minimal context
  -> portable pre-analysis snapshot
  -> local analysis computer
```

This is distinct from cross-machine scientific comparison. The user needs to
move data and source context off the control computer for deeper analysis
without depending on fragile local paths, memory, or the original machine.

## Evidence Basis

- `EV-044`: analysis handoff from a control computer to a user's analysis
  computer is a high-priority adoption pressure.
- `EV-045`: predecessor data-shape work provides validation coverage for
  handoff and durable-record journeys without deciding Scopecat storage,
  reader API, export format, or UI.
- `PN-004`: users need high-value data, source links, companion artifacts,
  corrections, and decisions to travel together.

Existing evidence shows users preserve Data Vault paths, numeric dataset IDs,
local file paths, and derived local snapshots inside analysis notebooks and
helpers. That supports source-identity and context-loss pressure; it does not
prove that a star/favorite UI already exists.

## Selection Guardrails

`JC-002` should prioritize internal full-fidelity handoff, keep ceremony low,
surface missing context, treat export as packaging over already-known artifacts,
and separate pre-analysis snapshots from later derived outputs.

It should not accept public/reference packaging, report generation, publication
workflow, full work-bundle import/export, live-monitor semantics, managed
analysis execution, permission systems, reader API signatures, storage, final
UI behavior, or manifest details.
