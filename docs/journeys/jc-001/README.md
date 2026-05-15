# JC-001

## Status

Entry point for the accepted passive evidence-view boundary. This folder is an
earned record for one validated slice, with supporting historical, design, and
prototype notes at their own validation levels.

## Purpose

`JC-001` validates a read-only passive evidence view for an existing experiment
work bundle:

```text
existing work bundle
  -> artifact roles
  -> evidence relations
  -> conflicts and missing facts
  -> sharing-aware report
```

The accepted boundary is fixture-sized, read-only, no execution, no mutation,
no hardware verification, no source-of-record authority, and no promoted
parser, storage, UI, runner, or subsystem ownership.

## Reading Order

| Order | Document | Use for |
| --- | --- | --- |
| 1 | [`journey.md`](journey.md) | User need, current-state pain, and future-state outcome. |
| 2 | [`decisions/passive-evidence-view.md`](decisions/passive-evidence-view.md) | Canonical accepted boundary, deferred scope, and reopening criteria. |
| 3 | [`prototypes/passive-evidence-view.md`](prototypes/passive-evidence-view.md) | Fixture-backed validation result and implementation-facing prototype scope. |
| 4 | [`contracts/evidence-view.md`](contracts/evidence-view.md) | Minimal vocabulary and report-shape contract used by the accepted slice. |
| 5 | [`contracts/manifest-and-public-output.md`](contracts/manifest-and-public-output.md) | Fixture manifest, public identity, and public-output redaction contract. |
| 6 | [`design-pressure.md`](design-pressure.md) | Design memory to preserve for later journeys without accepting a capability map. |
| 7 | [`selection.md`](selection.md) | Historical note on why this journey and fixture were selected. |

## Current State

The accepted slice has been validated by:

- a passive evidence-view decision;
- two committed public-safe fixtures;
- a read-only prototype that emits `evidence-view.json` and
  `evidence-view.md`;
- regression checks for fixture-local paths, role/relation coverage, conflicts,
  missing facts, and public-output redaction.

Cross-journey status is summarized in
[`../../status/progress-tracker.md`](../../status/progress-tracker.md).
`JC-001` reopen or extension detail belongs first in the decision, prototype,
contract, or design-pressure note before tracker coordination changes.
