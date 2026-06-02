# Discovery Slices

## Status

Navigation entry, not an inventory, roadmap, ADR, or implementation owner.

## Purpose

Discovery slice results record what one validation question earned and what it
did not earn. Use them as evidence, not as the active engineering planning
surface.

Active workflow sequencing belongs in
[`../../engineering/workflow-validation-map.md`](../../engineering/workflow-validation-map.md).
Accepted implementation ownership belongs in
[`../../engineering/vertical-slice-register.md`](../../engineering/vertical-slice-register.md).

The old flat slice inventory has moved to
[`../archive/slice-inventory.md`](../archive/slice-inventory.md). It remains
historical discovery evidence and a link-preserving index, but it should not be
used as a roadmap or as proof that candidate behavior should be copied into
live code.

## Current Use

When starting new discovery:

- start from the relevant problem brief or workflow map gap;
- create one narrow validation plan only when a new question needs it;
- write the validation result beside the route it informs;
- update the workflow map only if the result changes a named workflow step,
  seam, or risk question.

When promoting implementation:

- do not promote a slice directly from this directory;
- use the project phase model and vertical slice register;
- treat slice fixtures and expected outputs as evidence unless a promotion
  decision explicitly accepts them as active tests.
