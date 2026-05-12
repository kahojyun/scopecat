# JC-001 Document Set

## Status

Active first-wedge record.

## Purpose

Collect the durable `JC-001` journey, decision, prototype, and ownership notes
in one place.

`JC-001` is the accepted first wedge for explaining an existing work bundle as
a passive evidence view. The current validated boundary is read-only,
fixture-sized, no execution, no mutation, no hardware verification, no
source-of-record authority, and no package/parser/storage/UI promotion.

Use this folder as the pattern for later journey candidates: co-locate journey,
capability, wedge, contract, spike, decision, prototype, and ownership artifacts
as they are earned or promoted. Do not create the whole shape upfront.

## Reading Order

| Order | Document | Use for |
| --- | --- | --- |
| 1 | [`jc-001-journey-selection-note.md`](jc-001-journey-selection-note.md) | Why this journey and fixture boundary were selected. |
| 2 | [`jc-001-work-bundle-explanation-journey.md`](jc-001-work-bundle-explanation-journey.md) | Current-state and future-state user journey. |
| 3 | [`jc-001-capability-adoption-extraction.md`](jc-001-capability-adoption-extraction.md) | Capability pressure and standalone adoption steps. |
| 4 | [`jc-001-existing-bundle-to-explainable-context-wedge.md`](jc-001-existing-bundle-to-explainable-context-wedge.md) | First migration wedge shape. |
| 5 | [`jc-001-concepts-and-contracts.md`](jc-001-concepts-and-contracts.md) | Minimum concepts and cross-capability contracts. |
| 6 | [`jc-001-static-analysis-spike.md`](jc-001-static-analysis-spike.md) | Static-analysis spike result. |
| 7 | [`jc-001-passive-evidence-view-decision.md`](jc-001-passive-evidence-view-decision.md) | Accepted passive evidence-view boundary. |
| 8 | [`jc-001-passive-evidence-view-prototype-scope.md`](jc-001-passive-evidence-view-prototype-scope.md) | Two-fixture prototype scope and validation result. |
| 9 | [`jc-001-passive-evidence-view-capability-ownership.md`](jc-001-passive-evidence-view-capability-ownership.md) | Provisional ownership for accepted fact and contract families. |

## Current State

The first wedge has been validated through:

- an accepted passive evidence-view decision;
- a two-fixture read-only prototype;
- fixture-sized manifest validation and expected-shape checks;
- explicit validated-boundary and reopen criteria for the prototype;
- provisional capability ownership pressure for the accepted evidence-view facts.

The current next product/architecture choice is tracked in
[`../progressive-adoption-progress-tracker.md`](../progressive-adoption-progress-tracker.md).

## Reusable Pattern

Future JC folders should add only the next earned artifact. Start with
selection and journey notes; add capability, wedge, contract, spike, decision,
prototype, and ownership notes only when later evidence promotes them. Use
these questions as the sequence:

1. Why this journey and fixture boundary?
2. What current-state and future-state user journey is being tested?
3. Which capabilities are touched, and what is the smallest useful adoption
   step for each?
4. What is the thin migration wedge?
5. Which concepts and contracts are needed for that wedge?
6. What spike or prototype result validates the decision?
7. What is accepted, deferred, and reopened only with new evidence?
8. Which provisional owners are created by the accepted wedge?
