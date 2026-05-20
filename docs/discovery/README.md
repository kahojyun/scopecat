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

## Other Problem Briefs

These briefs are framed but do not yet have the same level of validation
artifacts in this branch:

| Brief | Use For |
| --- | --- |
| [`problem-briefs/parameter-state-history.md`](problem-briefs/parameter-state-history.md) | Mutable parameter files, run-linked snapshots, drift queries, bad states, and apply/review boundaries. |
| [`problem-briefs/experiment-code-selection.md`](problem-briefs/experiment-code-selection.md) | Copied folders, entrypoint ambiguity, code snapshots, environment validation, and code-version selection. |
| [`problem-briefs/selected-reference-comparison.md`](problem-briefs/selected-reference-comparison.md) | Selected references, known-good as a narrower subtype, setup reality, comparison findings, and scientific comparability limits. |

## Promotion Discipline

Do not promote a validation result directly into shared architecture.

Before moving a concept into accepted schema, shared implementation, or
`docs/architecture/`, make sure there is:

- pressure from more than one validated slice;
- a concrete implementation need;
- explicit tests or contracts that would otherwise be duplicated;
- a narrower decision or ADR that names the ownership and what remains out of
  scope.
