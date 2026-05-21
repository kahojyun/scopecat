# Discovery

## Purpose

Discovery owns current problem framing, adoption hypotheses, validation
artifacts, implementation-shaped exploration results, synthesis, and explicit
deferrals.

These documents are not user documentation and are not accepted architecture
unless a narrower document says so. Use them to decide the next validation or
implementation slice without promoting slice-local vocabulary into shared
product contracts too early.

## Read First

| Document | Use For |
| --- | --- |
| [`adoption-hypotheses.md`](adoption-hypotheses.md) | Compare current product-value hypotheses by user-visible behavior change. |
| [`problem-briefs/README.md`](problem-briefs/README.md) | Start from evidence-backed problem framing before choosing a validation question. |
| [`cross-slice-synthesis.md`](cross-slice-synthesis.md) | See recurring candidate concepts across validated slices. |
| [`shared-model-extraction-deferral.md`](shared-model-extraction-deferral.md) | Understand why shared domain models are intentionally deferred. |
| [`external-file-reference-policy.md`](external-file-reference-policy.md) | Candidate policy vocabulary for external files, latest state, observed file state, and non-backup boundaries. |

## Validation Slices

### Selected Measurement Export

| Document | Use For |
| --- | --- |
| [`problem-briefs/selected-run-handoff.md`](problem-briefs/selected-run-handoff.md) | Problem framing for selected-run handoff and export pressure. |
| [`problem-briefs/measurement-record-boundary.md`](problem-briefs/measurement-record-boundary.md) | Boundary pressure around primary measurement data, context, attachments, and artifacts. |
| [`selected-run-handoff-spike-summary.md`](selected-run-handoff-spike-summary.md) | Narrow spike summary before the preview-ready export consolidation. |
| [`selected-measurement-export-decision-summary.md`](selected-measurement-export-decision-summary.md) | Decision-ready discovery summary for preview-ready selected measurement export. |
| [`preview-ready-selected-measurement-export-plan.md`](preview-ready-selected-measurement-export-plan.md) | Planning boundary for the source/metadata-first export slice. |
| [`preview-ready-selected-measurement-export-implementation-plan.md`](preview-ready-selected-measurement-export-implementation-plan.md) | Code-facing plan for the pure selected measurement export summary builder. |
| [`preview-ready-selected-measurement-export-validation-result.md`](preview-ready-selected-measurement-export-validation-result.md) | Result of the first implementation-shaped export candidate. |
| [`storage-transition-export-fixture.md`](storage-transition-export-fixture.md) | Fixture note for managed storage, external references, source identity, and export materialization pressure. |
| [`storage-transition-export-validation-result.md`](storage-transition-export-validation-result.md) | Result of the storage-transition fixture and domain review. |
| [`external-file-reference-policy.md`](external-file-reference-policy.md) | Candidate external-file policy modes that affect export, import, inspection, and provenance. |

### Running Measurement Inspection

| Document | Use For |
| --- | --- |
| [`problem-briefs/running-measurement-inspection.md`](problem-briefs/running-measurement-inspection.md) | Problem framing for inspecting already-recorded data from a still-running measurement. |
| [`running-measurement-inspection-validation-plan.md`](running-measurement-inspection-validation-plan.md) | First fixture-validation boundary for running inspection. |
| [`running-measurement-inspection-validation-result.md`](running-measurement-inspection-validation-result.md) | Result of running-inspection fixture validation. |

### Calibration Work Continuation

| Document | Use For |
| --- | --- |
| [`problem-briefs/calibration-work-continuation.md`](problem-briefs/calibration-work-continuation.md) | Problem framing for calibration continuation, review gates, and executor pressure. |
| [`calibration-work-continuation-validation-plan.md`](calibration-work-continuation-validation-plan.md) | First fixture-validation boundary for continuation-state assembly. |
| [`calibration-work-continuation-validation-result.md`](calibration-work-continuation-validation-result.md) | Result of the continuation assembler candidate and domain review. |

### Parameter State Management

| Document | Use For |
| --- | --- |
| [`problem-briefs/parameter-state-management.md`](problem-briefs/parameter-state-management.md) | Problem framing for first-class calibrated parameter state, lineages, trust/readiness state, reviewable diffs, and write-back boundaries. |
| [`parameter-state-management-validation-plan.md`](parameter-state-management-validation-plan.md) | First fixture-validation boundary and fixture pointer for parameter state lineage, purpose labels, reviewable diffs, and committed states. |
| [`parameter-state-management-validation-result.md`](parameter-state-management-validation-result.md) | Result of the first parameter-state fixture and domain review. |

### Setup Binding

| Document | Use For |
| --- | --- |
| [`problem-briefs/setup-binding.md`](problem-briefs/setup-binding.md) | Problem framing for sample/cooldown binding between logical entities and physical wiring/device resources. |
| [`setup-binding-validation-plan.md`](setup-binding-validation-plan.md) | First fixture-validation boundary for setup-binding snapshots, diffs, and measurement references. |
| [`setup-binding-validation-result.md`](setup-binding-validation-result.md) | Result of the first setup-binding fixture and measurement-input context review. |

### Selected Reference Comparison

| Document | Use For |
| --- | --- |
| [`problem-briefs/selected-reference-comparison.md`](problem-briefs/selected-reference-comparison.md) | Problem framing for selected references, user marks, setup reality, objective comparison findings, and user-interpretation boundaries. |
| [`selected-reference-comparison-validation-plan.md`](selected-reference-comparison-validation-plan.md) | First fixture-validation boundary for selected-reference context comparison. |
| [`selected-reference-comparison-validation-result.md`](selected-reference-comparison-validation-result.md) | Result of the first selected-reference comparison fixture. |

## Other Problem Briefs

These briefs are framed but do not yet have the same level of validation
artifacts in this branch:

| Brief | Use For |
| --- | --- |
| [`problem-briefs/experiment-code-selection.md`](problem-briefs/experiment-code-selection.md) | Copied folders, entrypoint/helper ambiguity, selected code context, environment readiness, and code-version selection. |

## Promotion Discipline

Do not promote a validation result directly into shared architecture.

Before moving a concept into accepted schema, shared implementation, or
`docs/architecture/`, make sure there is:

- pressure from more than one validated slice;
- a concrete implementation need;
- explicit tests or contracts that would otherwise be duplicated;
- a narrower decision or ADR that names the ownership and what remains out of
  scope.
