# Discovery

## Purpose

Discovery owns current problem framing, adoption routes, validation
artifacts, implementation-shaped exploration results, synthesis, and explicit
deferrals.

These documents are not user documentation and are not accepted architecture
unless a narrower document says so. Use them to decide the next validation or
implementation slice without promoting slice-local vocabulary into shared
product contracts too early.

## Read First

| Document | Use For |
| --- | --- |
| [`doc-types.md`](doc-types.md) | Understand which discovery document type owns navigation, policies, route decisions, slice evidence, or synthesis. |
| [`../engineering/project-phase-model.md`](../engineering/project-phase-model.md) | Classify whether work is discovery, candidate, engineering prototype, production vertical slice, or supported workflow before promoting code. |
| [`../engineering/workflow-validation-map.md`](../engineering/workflow-validation-map.md) | Start from user workflow threads, validated steps, and missing seams before selecting the next prototype or vertical slice. |
| [`routes/README.md`](routes/README.md) | Navigate route owners, route decisions, and adoption routes by durable user workflow. |
| [`routes/prototype-promotion-map.md`](routes/prototype-promotion-map.md) | Coordinate route-by-route discovery-to-engineering prototype promotion status. |
| [`policies/README.md`](policies/README.md) | Navigate repeated boundary vocabulary and product posture documents. |
| [`problem-briefs/README.md`](problem-briefs/README.md) | Start from evidence-backed problem framing before choosing a validation question. |
| [`slices/README.md`](slices/README.md) | Browse the current discovery slice inventory by route and maturity. |
| [`synthesis/cross-slice.md`](synthesis/cross-slice.md) | See recurring candidate concepts, stable separations, and cross-route design pressure. |
| [`synthesis/shared-model-extraction-deferral.md`](synthesis/shared-model-extraction-deferral.md) | Understand why shared domain models are intentionally deferred. |
| [`synthesis/measurement-context-backlog.md`](synthesis/measurement-context-backlog.md) | Shared discovery backlog for context records attached to or selected for measurements, without accepting a shared schema. |

## Validation Slices

Validation slices are grouped by adoption route. A route can contain several
slices at different maturity levels; a slice should stay narrow even when it
tests part of a broader route.

The detailed slice inventory now lives in
[`slices/README.md`](slices/README.md). Keep this README focused on navigation
and use route indexes or route consolidation docs for route-specific
sequencing.

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

Use route owners for sequencing and detailed navigation. Keep this README as
the discovery landing page rather than a duplicate route inventory.

| Area | Owner |
| --- | --- |
| Measurement Records | [`routes/measurement-records/README.md`](routes/measurement-records/README.md) |
| Handoff packages | Current implementation owners are [`engineering-prototype-promotion-decision.md`](../architecture/handoff/engineering-prototype-promotion-decision.md), [`durable-import-storage-decision.md`](../architecture/handoff/durable-import-storage-decision.md), and [`src/scopecat/handoff/README.md`](../../src/scopecat/handoff/README.md); retired discovery synthesis remains in [`routes/measurement-records/handoff/README.md`](routes/measurement-records/handoff/README.md). |
| Import/source decisions | [`routes/measurement-records/import-source-decision.md`](routes/measurement-records/import-source-decision.md) |
| Experiment code | [`routes/experiment-code/README.md`](routes/experiment-code/README.md) |
| Environment operation | [`routes/environment-operation/README.md`](routes/environment-operation/README.md) |
| Parameter state | Current implementation owners are [`routes/parameter-state/README.md`](routes/parameter-state/README.md), [`engineering-prototype-promotion-decision.md`](../architecture/parameter-state/engineering-prototype-promotion-decision.md), and [`src/scopecat/parameter_state/README.md`](../../src/scopecat/parameter_state/README.md). |
| Measurement context backlog | [`synthesis/measurement-context-backlog.md`](synthesis/measurement-context-backlog.md) |
| Setup binding, calibration, selected reference | [`slices/README.md`](slices/README.md) plus the relevant problem brief in [`problem-briefs/`](problem-briefs/) |

## Promotion Discipline

Do not promote a validation result directly into shared architecture.

Before moving a concept into accepted schema, shared implementation, live route
code, or `docs/architecture/`, first classify the phase in
[`../engineering/project-phase-model.md`](../engineering/project-phase-model.md)
and attach the work to a named workflow step, seam, or risk question in
[`../engineering/workflow-validation-map.md`](../engineering/workflow-validation-map.md).
Then make sure there is:

- pressure from more than one validated slice;
- a concrete implementation need;
- explicit tests or contracts that would otherwise be duplicated;
- a narrower decision or ADR that names the ownership and what remains out of
  scope.
