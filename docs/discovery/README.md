# Discovery

## Purpose

Discovery owns problem framing, historical adoption-route evidence, validation
artifacts, implementation-shaped exploration results before promotion,
synthesis, and explicit deferrals.

These documents are not user documentation and are not accepted architecture
unless a narrower document says so. Use them to decide the next validation or
implementation slice without promoting slice-local vocabulary into shared
product contracts too early.

After discovery evidence starts moving into live route-local code, product
journey framing belongs in [`../product/target-journeys.md`](../product/target-journeys.md),
use case validation sequencing belongs in
[`../engineering/workflow-validation-map.md`](../engineering/workflow-validation-map.md),
product capability maturity belongs in
[`../product/target-capabilities.md`](../product/target-capabilities.md), and
implementation ownership belongs in
[`../engineering/implementation-register.md`](../engineering/implementation-register.md).
Discovery track and slice documents remain evidence and discovery status, not
the default owner for engineering-prototype expansion. The `routes/` directory
is a legacy path for discovery tracks, not an active product route map.

## Read First

| Document | Use For |
| --- | --- |
| [`doc-types.md`](doc-types.md) | Understand which discovery document type owns navigation, policies, track decisions, slice evidence, or synthesis. |
| [`../product/adoption-strategy.md`](../product/adoption-strategy.md) | Current product adoption paths. |
| [`../product/target-journeys.md`](../product/target-journeys.md) | Current target product user journeys, primary workflows, and use cases to prove before promotion. |
| [`../product/target-capabilities.md`](../product/target-capabilities.md) | Current target product capabilities, maturity, evidence, and open advancement questions. |
| [`../brownfield/README.md`](../brownfield/README.md) | Current-state, transition architecture, migration strategy, and migration roadmap for brownfield context. |
| [`../engineering/delivery-maturity-model.md`](../engineering/delivery-maturity-model.md) | Classify maturity owners before promoting code; treat candidates, spikes, prototypes, scenarios, and operations as evidence or validation methods. |
| [`../engineering/workflow-validation-map.md`](../engineering/workflow-validation-map.md) | Start from use case validation state, evidence scopes, and missing seams before selecting the next prototype or vertical slice. |
| [`routes/README.md`](routes/README.md) | Navigate discovery tracks, discovery decisions, and historical adoption-route evidence by durable user workflow. |
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

Validation slices are grouped by discovery track. A track can contain several
slices at different maturity levels; a slice should stay narrow even when it
tests part of a broader workflow or adoption path.

Keep this README focused on navigation and use discovery-track indexes or
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
owner of active sequencing. Current target journey framing belongs in
[`../product/target-journeys.md`](../product/target-journeys.md), and current
use case validation sequencing belongs in
[`../engineering/workflow-validation-map.md`](../engineering/workflow-validation-map.md).

## Discovery Track Pointers

Use [`routes/README.md`](routes/README.md) as the single discovery-track
inventory. This README should not repeat track tables; it only points to the
track inventory and to engineering owners for work that has moved into live
prototype implementation.

## Promotion Discipline

Before moving discovery evidence into accepted schema, shared implementation,
live route code, or `docs/engineering/prototype-boundaries/`, classify the work
in [`../engineering/delivery-maturity-model.md`](../engineering/delivery-maturity-model.md)
and attach it to a named journey in
[`../product/target-journeys.md`](../product/target-journeys.md), plus a use case,
workflow seam, evidence scope, or risk question in
[`../engineering/workflow-validation-map.md`](../engineering/workflow-validation-map.md).
Do not promote validation-result wording by copy/paste.
