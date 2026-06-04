# Discovery

## Purpose

Discovery owns problem framing, boundary policies, validation evidence,
implementation-shaped exploration results before promotion, compact historical
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
Discovery slice documents remain historical evidence, not the default owner
for engineering-prototype expansion. The former `routes/` directory has been
removed; product, brownfield, architecture, decision, and engineering owners
now own active routing and sequencing.

## Read First

| Document | Use For |
| --- | --- |
| [`doc-types.md`](doc-types.md) | Understand which discovery document type owns navigation, policies, slice evidence, or synthesis. |
| [`../product/adoption-strategy.md`](../product/adoption-strategy.md) | Current product adoption paths. |
| [`../product/target-journeys.md`](../product/target-journeys.md) | Current target product user journeys, primary workflows, and use cases to prove before promotion. |
| [`../product/target-capabilities.md`](../product/target-capabilities.md) | Current target product capabilities, maturity, evidence, and open advancement questions. |
| [`../brownfield/README.md`](../brownfield/README.md) | Current-state, transition architecture, migration strategy, and migration roadmap for brownfield context. |
| [`../engineering/delivery-maturity-model.md`](../engineering/delivery-maturity-model.md) | Classify maturity owners before promoting code; treat candidates, spikes, prototypes, scenarios, and operations as evidence or validation methods. |
| [`../engineering/workflow-validation-map.md`](../engineering/workflow-validation-map.md) | Start from use case validation state, evidence scopes, and missing seams before selecting the next use-case-driven prototype. |
| [`../engineering/implementation-register.md`](../engineering/implementation-register.md) | Current live implementation owners. |
| [`policies/README.md`](policies/README.md) | Navigate repeated boundary vocabulary, artifact classification, and product strategy documents. |
| [`problem-briefs/README.md`](problem-briefs/README.md) | Start from evidence-backed problem framing before choosing a validation question. |
| [`slices/README.md`](slices/README.md) | Understand the removed slice corpus and current archive policy. |
| [`synthesis/cross-slice.md`](synthesis/cross-slice.md) | See compact historical cross-slice design pressure after the detailed slice corpus removal. |
| [`synthesis/shared-model-extraction-deferral.md`](synthesis/shared-model-extraction-deferral.md) | Understand why shared domain models are intentionally deferred. |

## Historical Reference

Use [`archive/README.md`](archive/README.md) only when an active discovery owner
points to historical inventories, retired route synthesis, or frozen
coordination maps.

## Former Validation Slices

The former validation slice body corpus has been removed from active docs.
The compact historical index remains in
[`slice-inventory.md`](archive/slice-inventory.md), and Git history
preserves the deleted bodies.

Do not restart unbounded slice accumulation. New validation should start from
a brownfield entrypoint, architecture transition gap, target journey gap,
workflow/use-case validation question, or clearly scoped technical risk.
Write new validation material beside the current owner it informs unless a
narrow temporary plan/result file is clearly earned.

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

## Future Discovery Entry Points

Do not recreate discovery routes as the default organizing layer. New
discovery should start from one of the active owners:

- a brownfield entrypoint or migration gap in [`../brownfield/README.md`](../brownfield/README.md);
- a target journey or adoption gap in [`../product/target-journeys.md`](../product/target-journeys.md);
- a workflow/use-case validation gap in [`../engineering/workflow-validation-map.md`](../engineering/workflow-validation-map.md);
- an architecture transition gap in [`../architecture/transition-architecture.md`](../architecture/transition-architecture.md);
- an evidence-backed problem brief in [`problem-briefs/README.md`](problem-briefs/README.md);
- a focused artifact or boundary policy in [`policies/README.md`](policies/README.md).

## Promotion Discipline

Before moving discovery evidence into accepted schema, shared implementation,
live route code, or `docs/engineering/prototype-boundaries/`, classify the work
in [`../engineering/delivery-maturity-model.md`](../engineering/delivery-maturity-model.md)
and attach it to a named journey in
[`../product/target-journeys.md`](../product/target-journeys.md), plus a use case,
workflow seam, evidence scope, or risk question in
[`../engineering/workflow-validation-map.md`](../engineering/workflow-validation-map.md).
Do not promote validation-result wording by copy/paste.
