# Discovery

## Purpose

Discovery owns problem briefs and bounded validation guidance. Product,
brownfield, architecture, decision, and engineering docs own active direction,
sequencing, boundaries, and implementation ownership.

These documents are not user documentation, accepted architecture, validation
plans, or prototype-boundary owners unless a narrower current owner says so.
Use them to frame the next validation question without promoting historical
slice vocabulary into shared product contracts.

## Read First

| Document | Use For |
| --- | --- |
| [`../product/adoption-strategy.md`](../product/adoption-strategy.md) | Current product adoption paths. |
| [`../product/target-journeys.md`](../product/target-journeys.md) | Current target product user journeys, primary workflows, and use cases to prove before promotion. |
| [`../product/target-capabilities.md`](../product/target-capabilities.md) | Current target product capabilities, maturity, evidence, and open advancement questions. |
| [`../brownfield/README.md`](../brownfield/README.md) | Current-state, transition architecture, migration strategy, and migration roadmap for brownfield context. |
| [`../engineering/delivery-maturity-model.md`](../engineering/delivery-maturity-model.md) | Classify maturity owners before promoting code; treat candidates, spikes, prototypes, scenarios, and operations as evidence or validation methods. |
| [`../engineering/workflow-validation-map.md`](../engineering/workflow-validation-map.md) | Start from use case validation state, evidence scopes, and missing seams before selecting the next use-case-driven prototype. |
| [`../engineering/implementation-register.md`](../engineering/implementation-register.md) | Current live implementation owners. |
| [`problem-briefs/README.md`](problem-briefs/README.md) | Start from evidence-backed problem framing before choosing a validation question. |

## Historical Reference

Use [`archive/slice-inventory.md`](archive/slice-inventory.md) only when a
current owner points to historical validation-slice evidence. Git history
preserves the deleted slice bodies.

Do not restart unbounded slice accumulation. New validation should start from a
brownfield entrypoint, architecture boundary gap, target journey gap,
workflow/use-case validation question, or clearly scoped technical risk. Write
new validation material beside the current owner it informs unless a narrow
temporary plan/result file is clearly earned.

Discovery fixtures and expected outputs are repository-safe artifacts by
default, not automatically portable/public/export artifacts. Use
[`../architecture/artifact-boundary-and-redaction.md`](../architecture/artifact-boundary-and-redaction.md)
when deciding whether a slice needs runtime redaction, managed-reference
validation, a review-summary projection, or portable/package redaction rules.
For handoff package writers, the generated package directory is the portable
artifact, `package-manifest.json` is the portable contract/index inside that
directory, and any function return value is local/review-only unless the slice
declares otherwise.

## Future Discovery Entry Points

Do not recreate discovery routes as the default organizing layer. New
discovery should start from one of the active owners:

- a brownfield entrypoint or migration gap in [`../brownfield/README.md`](../brownfield/README.md);
- a target journey or adoption gap in [`../product/target-journeys.md`](../product/target-journeys.md);
- a workflow/use-case validation gap in [`../engineering/workflow-validation-map.md`](../engineering/workflow-validation-map.md);
- an architecture boundary gap in [`../architecture/README.md`](../architecture/README.md);
- an evidence-backed problem brief in [`problem-briefs/README.md`](problem-briefs/README.md).

## Promotion Discipline

Before moving discovery evidence into accepted schema, shared implementation,
live route code, or `docs/engineering/prototype-boundaries/`, classify the work
in [`../engineering/delivery-maturity-model.md`](../engineering/delivery-maturity-model.md)
and attach it to a named journey in
[`../product/target-journeys.md`](../product/target-journeys.md), plus a use case,
workflow seam, evidence scope, or risk question in
[`../engineering/workflow-validation-map.md`](../engineering/workflow-validation-map.md).
Do not promote validation-result wording by copy/paste.
