# JC-001

## Status

Accepted first journey record. This is an index and history status, not a
shared validation status for every artifact in this folder.

## Purpose

Collect the durable `JC-001` journey, slice, decision, prototype, contract, and
design-pressure notes in one place.

`JC-001` is the accepted first slice for explaining an existing work bundle as
a passive evidence view. The validated boundary is read-only, fixture-sized, no
execution, no mutation, no hardware verification, no source-of-record
authority, and no package/parser/storage/UI promotion.

Use this folder as an earned exemplar for later journey candidates, not as a
packet to copy wholesale.

## Reading Order

| Order | Document | Type | Use for |
| --- | --- | --- | --- |
| 1 | [`selection.md`](selection.md) | Selection | Why this journey and fixture boundary were selected. |
| 2 | [`journey.md`](journey.md) | Journey | Current-state and future-state user journey. |
| 3 | [`design-pressure.md`](design-pressure.md) | Design pressure | Product-value and design-pressure memory preserved from this journey. |
| 4 | [`slices/passive-evidence-view.md`](slices/passive-evidence-view.md) | Slice | Accepted validation slice shape. |
| 5 | [`contracts/evidence-view.md`](contracts/evidence-view.md) | Contract | Minimum concepts and cross-pressure contracts. |
| 6 | [`prototypes/static-analysis-spike.md`](prototypes/static-analysis-spike.md) | Prototype | Static-analysis spike result. |
| 7 | [`decisions/passive-evidence-view.md`](decisions/passive-evidence-view.md) | Decision | Accepted passive evidence-view boundary. |
| 8 | [`prototypes/passive-evidence-view.md`](prototypes/passive-evidence-view.md) | Prototype | Two-fixture prototype scope and validation result. |
| 9 | [`contracts/manifest-and-public-output.md`](contracts/manifest-and-public-output.md) | Contract | Fixture-validated manifest, public identity, and public-output redaction contract. |
| 10 | [`contracts/design-pressure-ownership.md`](contracts/design-pressure-ownership.md) | Contract | Provisional design-pressure ownership for accepted fact and contract families. |

## Audience Read Paths

| Audience | Read path |
| --- | --- |
| Product or history reader | Selection -> journey -> slice -> decision. |
| Implementation reviewer | Decision -> prototype scope -> manifest/public-output contract -> static-analysis spike -> evidence-view contract. |
| Architecture reviewer | Evidence-view contract -> design-pressure ownership -> decision -> tracker status. |

## Current State

The first slice has been validated through:

- an accepted passive evidence-view decision;
- a two-fixture read-only prototype;
- fixture-sized manifest validation and expected-shape checks;
- a fixture-validated manifest and public-output identity contract;
- explicit validated-boundary and reopen criteria for the prototype;
- provisional design-pressure ownership for the accepted evidence-view facts.

Cross-journey coordination that depends on `JC-001` is summarized in
[`../../status/progress-tracker.md`](../../status/progress-tracker.md), but
`JC-001` reopen or extension detail should be recorded in the owning decision,
slice, prototype, contract, or design-pressure document before tracker
coordination is updated.

## Exemplar Boundary

This folder is an example of how later artifacts can accumulate after evidence
earns them. It should not be copied wholesale for a new journey candidate.
