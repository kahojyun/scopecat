# Discovery Slice Archive Pointer

## Status

Historical slice archive pointer.

## Purpose

The detailed discovery slice body corpus has been removed from the active
documentation tree. Git history preserves the old validation plans,
validation results, implementation-plan notes, and fixture-shaped summaries.

Use this README only as a pointer to the compact historical index and to the
current owners for architecture, workflow validation, capability maturity, and
implementation ownership.

Product journey framing belongs in
[`../../product/target-journeys.md`](../../product/target-journeys.md).
Use case validation sequencing belongs in
[`../../engineering/workflow-validation-map.md`](../../engineering/workflow-validation-map.md).
Capability maturity belongs in
[`../../product/target-capabilities.md`](../../product/target-capabilities.md).
Implementation ownership belongs in
[`../../engineering/implementation-register.md`](../../engineering/implementation-register.md).

The compact historical index lives in
[`slice-inventory.md`](../archive/slice-inventory.md). It is not a
link-preserving mirror of the deleted slice bodies; use Git history if a
specific removed slice body is needed.

## Current Use

When starting new discovery:

- start from the relevant brownfield entrypoint, problem brief, target journey
  gap, architecture transition gap, or workflow/use-case validation map gap;
- create one narrow validation plan only when a new question needs it;
- write the validation result beside the current owner it informs, not in a
  new unbounded slice corpus by default;
- update the target journey map only if the result changes a target user
  journey, workflow, or use case;
- update the brownfield transition architecture only if the result changes
  current-state, transition-state, migration, or ownership-posture claims;
- update the architecture docs only if the result changes the brownfield
  entrypoint model, domain model, context map, or slice classification frame;
- update the workflow validation map only if the result changes a named use
  case, workflow seam, evidence scope, or risk question.

When promoting implementation:

- do not promote a slice directly from this directory;
- use the delivery maturity model and target capability map;
- treat slice fixtures and expected outputs as evidence unless a promotion
  decision explicitly accepts them as active tests.
