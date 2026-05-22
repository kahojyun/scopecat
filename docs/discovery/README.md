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
| [`adoption-routes.md`](adoption-routes.md) | Compare current evidence-backed adoption routes by durable user workflow. |
| [`problem-briefs/README.md`](problem-briefs/README.md) | Start from evidence-backed problem framing before choosing a validation question. |
| [`cross-slice-synthesis.md`](cross-slice-synthesis.md) | See recurring candidate concepts across validated slices. |
| [`shared-model-extraction-deferral.md`](shared-model-extraction-deferral.md) | Understand why shared domain models are intentionally deferred. |
| [`external-file-reference-policy.md`](external-file-reference-policy.md) | Candidate policy vocabulary for external files, latest state, observed file state, and non-backup boundaries. |
| [`managed-experiment-code-posture.md`](managed-experiment-code-posture.md) | Product posture for Git-like managed experiment-code versions without requiring users to operate Git. |

## Validation Slices

Validation slices are grouped by adoption route. A route can contain several
slices at different maturity levels; a slice should stay narrow even when it
tests part of a broader route.

### Measurement Records

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
| [`problem-briefs/running-measurement-inspection.md`](problem-briefs/running-measurement-inspection.md) | Problem framing for inspecting already-recorded data from a still-running measurement. |
| [`running-measurement-inspection-validation-plan.md`](running-measurement-inspection-validation-plan.md) | First fixture-validation boundary for running inspection. |
| [`running-measurement-inspection-validation-result.md`](running-measurement-inspection-validation-result.md) | Result of running-inspection fixture validation. |

Candidate next slices in this route include import preview, offline legacy-record
import, derived-analysis trace to source measurements and recorded analysis
choices, and new-run measurement writer semantics.

### Parameter State

| Document | Use For |
| --- | --- |
| [`problem-briefs/parameter-state-management.md`](problem-briefs/parameter-state-management.md) | Problem framing for first-class calibrated parameter state, lineages, trust/readiness state, reviewable diffs, and write-back boundaries. |
| [`parameter-state-management-validation-plan.md`](parameter-state-management-validation-plan.md) | First fixture-validation boundary and fixture pointer for parameter state lineage, purpose labels, reviewable diffs, and committed states. |
| [`parameter-state-management-validation-result.md`](parameter-state-management-validation-result.md) | Result of the first parameter-state fixture and domain review. |

Candidate next slices in this route include reviewable parameter-write records,
compatibility JSON writer behavior, drift views, and calibration-step links to
selected parameter states.

### Experiment Code Context

| Document | Use For |
| --- | --- |
| [`problem-briefs/experiment-code-selection.md`](problem-briefs/experiment-code-selection.md) | Copied folders, entrypoint/helper ambiguity, selected code context, environment readiness, and code-version selection. |
| [`managed-experiment-code-posture.md`](managed-experiment-code-posture.md) | Direction for messy external-folder import, Scopecat-managed captured versions, named entrypoints, and workflow/DAG deferral. |
| [`experiment-code-selection-validation-plan.md`](experiment-code-selection-validation-plan.md) | First fixture-validation boundary for selected code context and captured-version candidates. |
| [`experiment-code-selection-validation-result.md`](experiment-code-selection-validation-result.md) | Result of the first selected-code context fixture and summary candidate. |
| [`experiment-code-selection-next-boundary.md`](experiment-code-selection-next-boundary.md) | What the code-selection slice has earned, what remains deferred, and what should trigger managed-workspace or environment-restore validation. |
| [`managed-code-version-validation-plan.md`](managed-code-version-validation-plan.md) | First fixture-validation boundary for turning a captured-version candidate into a managed code-version record. |
| [`managed-code-version-validation-result.md`](managed-code-version-validation-result.md) | Result of the first managed code-version fixture and summary candidate. |

Candidate next slices in this route include selected-version comparison,
workspace materialization intent, environment-readiness records, and later
loading of selected versions.

### Setup Binding

| Document | Use For |
| --- | --- |
| [`problem-briefs/setup-binding.md`](problem-briefs/setup-binding.md) | Problem framing for sample/cooldown binding between logical entities and physical wiring/device resources. |
| [`setup-binding-validation-plan.md`](setup-binding-validation-plan.md) | First fixture-validation boundary for setup-binding snapshots, diffs, and measurement references. |
| [`setup-binding-validation-result.md`](setup-binding-validation-result.md) | Result of the first setup-binding fixture and measurement-input context review. |

Candidate next slices in this route include setup-binding comparison,
setup-import validation reports, run-start named input snapshots, and
selected-reference setup findings.

### Calibration Continuation

| Document | Use For |
| --- | --- |
| [`problem-briefs/calibration-work-continuation.md`](problem-briefs/calibration-work-continuation.md) | Problem framing for calibration continuation, review gates, and executor pressure. |
| [`calibration-work-continuation-validation-plan.md`](calibration-work-continuation-validation-plan.md) | First fixture-validation boundary for continuation-state assembly. |
| [`calibration-work-continuation-validation-result.md`](calibration-work-continuation-validation-result.md) | Result of the continuation assembler candidate and domain review. |

Candidate next slices in this route include a local sequential executor
boundary, review/resume UX, calibration-write review, selected-group
remeasurement, and links to parameter states and measurement records.

### Selected Reference Comparison

| Document | Use For |
| --- | --- |
| [`problem-briefs/selected-reference-comparison.md`](problem-briefs/selected-reference-comparison.md) | Problem framing for selected references, user marks, setup reality, objective comparison findings, and user-interpretation boundaries. |
| [`selected-reference-comparison-validation-plan.md`](selected-reference-comparison-validation-plan.md) | Fixture-validation boundaries for selected-reference context comparison. |
| [`selected-reference-comparison-validation-result.md`](selected-reference-comparison-validation-result.md) | Result of selected-reference context comparison fixtures, including the basic named-input fixture and the declared selected-code context comparison fixture. |

Candidate next slices in this route include deeper source-diff semantics,
restore/readiness comparison, setup-binding findings, parameter-state drift
findings, import/export comparison preview, and support-package review
boundaries.

## Promotion Discipline

Do not promote a validation result directly into shared architecture.

Before moving a concept into accepted schema, shared implementation, or
`docs/architecture/`, make sure there is:

- pressure from more than one validated slice;
- a concrete implementation need;
- explicit tests or contracts that would otherwise be duplicated;
- a narrower decision or ADR that names the ownership and what remains out of
  scope.
