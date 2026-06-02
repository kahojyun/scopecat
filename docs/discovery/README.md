# Discovery

## Purpose

Discovery owns problem framing, historical adoption-route evidence, validation
artifacts, implementation-shaped exploration results before promotion,
synthesis, and explicit deferrals.

These documents are not user documentation and are not accepted architecture
unless a narrower document says so. Use them to decide the next validation or
implementation slice without promoting slice-local vocabulary into shared
product contracts too early.

After discovery evidence starts moving into live route-local code, active
workflow sequencing belongs in
[`../engineering/workflow-validation-map.md`](../engineering/workflow-validation-map.md)
product capability maturity belongs in
[`../product/capability-map.md`](../product/capability-map.md), and
implementation ownership belongs in
[`../engineering/implementation-register.md`](../engineering/implementation-register.md).
Discovery route and slice documents remain evidence and discovery status, not
the default owner for engineering-prototype expansion.

## Read First

| Document | Use For |
| --- | --- |
| [`doc-types.md`](doc-types.md) | Understand which discovery document type owns navigation, policies, route decisions, slice evidence, or synthesis. |
| [`../product/adoption-model.md`](../product/adoption-model.md) | Current product adoption paths and brownfield migration boundaries. |
| [`../product/capability-map.md`](../product/capability-map.md) | Current product capabilities, maturity, evidence, and open advancement questions. |
| [`../engineering/delivery-maturity-model.md`](../engineering/delivery-maturity-model.md) | Classify workflow and capability maturity before promoting code; treat candidates, spikes, prototypes, and scenarios as validation methods. |
| [`../engineering/workflow-validation-map.md`](../engineering/workflow-validation-map.md) | Start from user workflow threads, validated steps, and missing seams before selecting the next prototype or vertical slice. |
| [`routes/README.md`](routes/README.md) | Navigate discovery route owners, route decisions, and historical adoption-route evidence by durable user workflow. |
| [`../engineering/implementation-register.md`](../engineering/implementation-register.md) | Current live implementation owners. |
| [`policies/README.md`](policies/README.md) | Navigate repeated boundary vocabulary, artifact classification, and product strategy documents. |
| [`problem-briefs/README.md`](problem-briefs/README.md) | Start from evidence-backed problem framing before choosing a validation question. |
| [`slices/README.md`](slices/README.md) | Use discovery slice results as evidence. |
| [`synthesis/cross-slice.md`](synthesis/cross-slice.md) | See recurring candidate concepts, stable separations, and cross-route design pressure. |
| [`synthesis/shared-model-extraction-deferral.md`](synthesis/shared-model-extraction-deferral.md) | Understand why shared domain models are intentionally deferred. |
| [`synthesis/measurement-context-backlog.md`](synthesis/measurement-context-backlog.md) | Shared discovery backlog for context records attached to or selected for measurements, without accepting a shared schema. |

## Historical Reference

Use [`archive/README.md`](archive/README.md) only when an active discovery owner
points to historical inventories, retired route synthesis, or frozen
coordination maps.

## Validation Slices

Validation slices are grouped by discovery route. A route can contain several
slices at different maturity levels; a slice should stay narrow even when it
tests part of a broader workflow or adoption path.

Keep this README focused on navigation and use route indexes or route
consolidation docs for discovery-specific sequencing. The old flat slice
inventory remains in [`archive/slice-inventory.md`](archive/slice-inventory.md)
for historical reference.

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
owner of active sequencing. Current workflow sequencing belongs in
[`../engineering/workflow-validation-map.md`](../engineering/workflow-validation-map.md).

## Route Pointers

Use [`routes/README.md`](routes/README.md) as the single discovery route
inventory. This README should not repeat route owner tables; it only points to
the route inventory and to engineering owners for work that has moved into live
prototype implementation.

## Promotion Discipline

Before moving discovery evidence into accepted schema, shared implementation,
live route code, or `docs/engineering/prototype-boundaries/`, classify the work
in [`../engineering/delivery-maturity-model.md`](../engineering/delivery-maturity-model.md)
and attach it to a named workflow step, seam, or risk question in
[`../engineering/workflow-validation-map.md`](../engineering/workflow-validation-map.md).
Do not promote validation-result wording by copy/paste.
