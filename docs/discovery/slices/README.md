# Discovery Slices

## Status

Discovery slice evidence entry.

## Purpose

Discovery slice results record what one validation question earned and what it
did not earn. Use them as evidence, not as the active engineering planning
surface.

Product journey framing belongs in
[`../../product/journey-map.md`](../../product/journey-map.md).
Use case validation sequencing belongs in
[`../../engineering/workflow-validation-map.md`](../../engineering/workflow-validation-map.md).
Capability maturity belongs in
[`../../product/capability-map.md`](../../product/capability-map.md).
Implementation ownership belongs in
[`../../engineering/implementation-register.md`](../../engineering/implementation-register.md).

The old flat slice inventory has moved to
[`../archive/slice-inventory.md`](../archive/slice-inventory.md). It remains
historical discovery evidence and a link-preserving index, but it should not be
used as a roadmap or as proof that candidate behavior should be copied into
live code.

## Current Use

When starting new discovery:

- start from the relevant problem brief, journey map gap, or workflow/use-case
  validation map gap;
- create one narrow validation plan only when a new question needs it;
- write the validation result beside the route it informs;
- update the journey map only if the result changes a user journey, workflow,
  or use case; update the workflow validation map only if the result changes a
  named use case, workflow seam, evidence scope, or risk question.

When promoting implementation:

- do not promote a slice directly from this directory;
- use the delivery maturity model and capability map;
- treat slice fixtures and expected outputs as evidence unless a promotion
  decision explicitly accepts them as active tests.
