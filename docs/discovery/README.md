# Discovery

## Purpose

Discovery owns problem framing, adoption routes, validation artifacts,
implementation-shaped exploration results before promotion, synthesis, and
explicit deferrals.

These documents are not user documentation and are not accepted architecture
unless a narrower document says so. Use them to decide the next validation or
implementation slice without promoting slice-local vocabulary into shared
product contracts too early.

After discovery evidence starts moving into live route-local code, active
workflow sequencing belongs in
[`../engineering/workflow-validation-map.md`](../engineering/workflow-validation-map.md)
and implementation ownership belongs in
[`../engineering/vertical-slice-register.md`](../engineering/vertical-slice-register.md).
Discovery route and slice documents remain evidence and discovery posture, not
the default owner for engineering-prototype expansion.

## Read First

| Document | Use For |
| --- | --- |
| [`doc-types.md`](doc-types.md) | Understand which discovery document type owns navigation, policies, route decisions, slice evidence, or synthesis. |
| [`../engineering/project-phase-model.md`](../engineering/project-phase-model.md) | Classify whether work is discovery, candidate, engineering prototype, production vertical slice, or supported workflow before promoting code. |
| [`../engineering/workflow-validation-map.md`](../engineering/workflow-validation-map.md) | Start from user workflow threads, validated steps, and missing seams before selecting the next prototype or vertical slice. |
| [`routes/README.md`](routes/README.md) | Navigate discovery route owners, route decisions, and adoption routes by durable user workflow. |
| [`../engineering/vertical-slice-register.md`](../engineering/vertical-slice-register.md) | Current accepted implementation slice ownership; the old promotion coordination map is archived at [`archive/prototype-promotion-map.md`](archive/prototype-promotion-map.md). |
| [`policies/README.md`](policies/README.md) | Navigate repeated boundary vocabulary and product posture documents. |
| [`problem-briefs/README.md`](problem-briefs/README.md) | Start from evidence-backed problem framing before choosing a validation question. |
| [`slices/README.md`](slices/README.md) | Use discovery slice results as evidence; the old flat inventory is archived at [`archive/slice-inventory.md`](archive/slice-inventory.md). |
| [`synthesis/cross-slice.md`](synthesis/cross-slice.md) | See recurring candidate concepts, stable separations, and cross-route design pressure. |
| [`synthesis/shared-model-extraction-deferral.md`](synthesis/shared-model-extraction-deferral.md) | Understand why shared domain models are intentionally deferred. |
| [`synthesis/measurement-context-backlog.md`](synthesis/measurement-context-backlog.md) | Shared discovery backlog for context records attached to or selected for measurements, without accepting a shared schema. |
| [`archive/README.md`](archive/README.md) | Find historical inventories, retired route synthesis, and frozen coordination maps after their active ownership moves elsewhere. |

## Validation Slices

Validation slices are grouped by adoption route. A route can contain several
slices at different maturity levels; a slice should stay narrow even when it
tests part of a broader route.

The old flat slice inventory is archived at
[`archive/slice-inventory.md`](archive/slice-inventory.md). Keep this README
focused on navigation and use route indexes or route consolidation docs for
discovery-specific sequencing.

Future slice candidates should each answer one primary validation question. Do
not combine import/export, storage, GUI, execution, redaction, write-back,
restore, or shared-framework decisions just because the same fixture mentions
more than one of them.

Discovery fixtures and expected outputs are repository-safe artifacts by
default, not automatically portable/public/export artifacts. Use
[`policies/artifact-boundary-and-redaction.md`](policies/artifact-boundary-and-redaction.md)
when deciding whether a slice needs runtime redaction, managed-reference
validation, a review-summary projection, or portable/package redaction rules.
For handoff package writers, the generated package directory is the portable
artifact, `package-manifest.json` is the portable contract/index inside that
directory, and any function return value is local/review-only unless the slice
declares otherwise.

Validation result and plan documents may include slice-local recommendations
for what their fixture earned or deferred. They should not be treated as the
owner of active sequencing. Sequencing belongs in the implementation or PR
plan, using these discovery docs as supporting context.

## Route Pointers

Use [`routes/README.md`](routes/README.md) as the single discovery route
inventory. This README should not repeat route owner tables; it only points to
the route inventory and to engineering owners for work that has moved into live
prototype implementation.

## Promotion Discipline

Do not promote a validation result directly into shared product or engineering
boundaries.

Before moving a concept into accepted schema, shared implementation, live route
code, or `docs/engineering/prototype-boundaries/`, first classify the phase in
[`../engineering/project-phase-model.md`](../engineering/project-phase-model.md)
and attach the work to a named workflow step, seam, or risk question in
[`../engineering/workflow-validation-map.md`](../engineering/workflow-validation-map.md).
Then make sure there is:

- pressure from more than one validated slice;
- a concrete implementation need;
- explicit tests or contracts that would otherwise be duplicated;
- a narrower decision or ADR that names the ownership and what remains out of
  scope.
