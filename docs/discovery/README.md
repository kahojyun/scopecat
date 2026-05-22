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

The route tables below include problem briefs, plans, validation results, and
supporting policy notes. The current validated slice inventory is:

| Slice | Route | Current maturity | Boundary |
| --- | --- | --- | --- |
| Preview-ready selected measurement export | Measurement records | Implementation candidate validated | Pure summary for explicit selected measurement sets, default bundles, linked context, declared preview metadata, degraded-preview warnings, and non-recursive traversal. |
| Storage-transition export | Measurement records | Fixture validated | Source identity, current reference, package materialization, and external-reference policy pressure without accepting storage, checksum, backup, package writer, importer, or GUI behavior. |
| Running measurement inspection | Measurement records | Fixture validated | State summary for already-recorded data from still-running measurements, including progress, completeness, freshness, declared preview metadata, and non-durable monitor ergonomics. |
| Declared scan/data-shape fixtures | Measurement records support | Spike/fixtures validated | Declared 1D table, rectangular 2D grid table, and sidecar-declared weak-table pressure for preview readiness, not a final data-shape schema or importer. |
| Parameter state management | Parameter state | Fixture validated | Parameter-state lineage, purpose labels, seeded/trusted state, reviewable diffs, committed states, and measurement references without hardware write-back or branch/tag/commit semantics. |
| Experiment code recording | Experiment code context | Summary candidate validated | Recorded run/step code context and code snapshot record from explicit include policy without Git inspection, dependency discovery, environment restore, loading, execution, or workflow/DAG semantics. |
| Managed code version | Experiment code context | Summary candidate validated | Managed record shape for a code snapshot record, including stable identity, inclusion-aligned file inventory, integrity hints, and materialization intent without workspace creation or environment restore. |
| Setup binding | Setup binding | Fixture validated | Setup-binding snapshots, simple diffs, station-registry references, generated line/readout views, and measurement input references while keeping parameter state and hardware control separate. |
| Calibration work continuation | Calibration continuation | Assembler candidate validated | Continuation-state assembly for planned steps, observed outputs, review gates, proposed writes, blocked steps, and interventions without executor, scheduler, write-back, or GUI ownership. |
| Selected reference comparison | Selected reference comparison | Fixtures validated | Context-comparison findings against a user-selected reference without user judgment, raw-data comparison, fit-quality comparison, setup truth, restore, execution, semantic source diff, or cause attribution. |

Future slice candidates should each answer one primary validation question. Do
not combine import/export, storage, GUI, execution, redaction, write-back,
restore, or shared-framework decisions just because the same fixture mentions
more than one of them.

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
| [`../../spikes/scan_data_shapes/README.md`](../../spikes/scan_data_shapes/README.md) | Spike boundary for declared scan/data-shape fixture generation. |
| [`../../tests/fixtures/scan_data_shapes/`](../../tests/fixtures/scan_data_shapes/) | Public-safe fixtures for rectangular 2D grid and sidecar-declared weak-table pressure. |
| [`problem-briefs/running-measurement-inspection.md`](problem-briefs/running-measurement-inspection.md) | Problem framing for inspecting already-recorded data from a still-running measurement. |
| [`running-measurement-inspection-validation-plan.md`](running-measurement-inspection-validation-plan.md) | First fixture-validation boundary for running inspection. |
| [`running-measurement-inspection-validation-result.md`](running-measurement-inspection-validation-result.md) | Result of running-inspection fixture validation. |

Candidate next slices in this route should stay separate:

- import preview: preview and classify incoming records before acceptance,
  without validating a full importer, storage mutation, or GUI workflow;
- offline legacy-record import: read or declare one legacy source shape and
  preserve source identity, without deciding export-package acceptance;
- derived artifact source links: connect a derived artifact to explicit source
  measurements, without recursive analysis-DAG inference;
- recorded analysis choices: capture user-declared analysis choices or saved
  decisions, without scientific interpretation or cause attribution;
- new-run measurement writer semantics: record new measurement data and
  lifecycle events, without taking over instrument control or live-advice
  behavior.

### Parameter State

| Document | Use For |
| --- | --- |
| [`problem-briefs/parameter-state-management.md`](problem-briefs/parameter-state-management.md) | Problem framing for first-class calibrated parameter state, lineages, trust/readiness state, reviewable diffs, and write-back boundaries. |
| [`parameter-state-management-validation-plan.md`](parameter-state-management-validation-plan.md) | First fixture-validation boundary and fixture pointer for parameter state lineage, purpose labels, reviewable diffs, and committed states. |
| [`parameter-state-management-validation-result.md`](parameter-state-management-validation-result.md) | Result of the first parameter-state fixture and domain review. |

Candidate next slices in this route should stay separate:

- reviewable parameter-write records: represent proposed and accepted changes
  without applying them to hardware;
- compatibility JSON writer behavior: produce or update an external compatibility
  file after review, without making that file the product authority;
- drift views: compare trusted parameter states over time, without accepting a
  final plotting model or branch/tag/commit semantics;
- calibration-step links to selected parameter states: reference selected state
  versions from calibration steps, without merging parameter state into a
  generic step-context framework.

### Experiment Code Context

| Document | Use For |
| --- | --- |
| [`problem-briefs/experiment-code-recording.md`](problem-briefs/experiment-code-recording.md) | Copied folders, entrypoint/helper ambiguity, recorded run/step code context, environment readiness, and future code snapshot selection. |
| [`managed-experiment-code-posture.md`](managed-experiment-code-posture.md) | Direction for messy external-folder recording, Scopecat-managed code versions, named entrypoints, and workflow/DAG deferral. |
| [`experiment-code-recording-validation-plan.md`](experiment-code-recording-validation-plan.md) | First fixture-validation boundary for recorded code context that defines code snapshot records. |
| [`experiment-code-recording-validation-result.md`](experiment-code-recording-validation-result.md) | Result of the first code snapshot fixture and summary candidate. |
| [`experiment-code-recording-next-boundary.md`](experiment-code-recording-next-boundary.md) | What the code-recording slice has earned, what remains deferred, and what should trigger managed-workspace or environment-restore validation. |
| [`managed-code-version-validation-plan.md`](managed-code-version-validation-plan.md) | First fixture-validation boundary for turning a code snapshot record into a managed code version record. |
| [`managed-code-version-validation-result.md`](managed-code-version-validation-result.md) | Result of the first managed code version fixture and summary candidate. |

Candidate next slices in this route should stay separate:

- selected-version comparison: compare a current editable folder or declared
  code context with a selected code snapshot or managed code version, without
  semantic source diff or Git workflow semantics;
- workspace materialization intent: plan where a selected version would be
  materialized, without creating an editable workspace;
- workspace materialization: create a selected version workspace, without
  environment sync, code import, or execution;
- environment-readiness records: check declared environment files or lockfiles
  only after materialization/storage boundaries are clearer, without importing
  hardware-active modules;
- selected-version loading: load or select a version for a workflow only after
  materialization and readiness are validated separately.

### Setup Binding

| Document | Use For |
| --- | --- |
| [`problem-briefs/setup-binding.md`](problem-briefs/setup-binding.md) | Problem framing for sample/cooldown binding between logical entities and physical wiring/device resources. |
| [`setup-binding-validation-plan.md`](setup-binding-validation-plan.md) | First fixture-validation boundary for setup-binding snapshots, diffs, and measurement references. |
| [`setup-binding-validation-result.md`](setup-binding-validation-result.md) | Result of the first setup-binding fixture and measurement-input context review. |

Candidate next slices in this route should stay separate:

- setup-binding comparison: compare two known binding snapshots, without
  importing external setup state or deciding parameter invalidation;
- setup-import validation reports: validate one external/generated setup source,
  without accepting a final setup schema or station-management model;
- run-start named input snapshots: pressure the measurement-context shape,
  without introducing a universal snapshot framework;
- selected-reference setup findings: surface objective setup-binding comparison
  facts for selected-reference review, without claiming setup truth.

### Calibration Continuation

| Document | Use For |
| --- | --- |
| [`problem-briefs/calibration-work-continuation.md`](problem-briefs/calibration-work-continuation.md) | Problem framing for calibration continuation, review gates, and executor pressure. |
| [`calibration-work-continuation-validation-plan.md`](calibration-work-continuation-validation-plan.md) | First fixture-validation boundary for continuation-state assembly. |
| [`calibration-work-continuation-validation-result.md`](calibration-work-continuation-validation-result.md) | Result of the continuation assembler candidate and domain review. |

Candidate next slices in this route should stay separate:

- review/resume usefulness: validate whether assembled continuation state is
  enough for a user to resume work, without building an executor or GUI;
- calibration-write review: represent proposed, accepted, rejected, and applied
  writes, without Scopecat-decided mutation or rollback;
- selected-group remeasurement: request or record targeted remeasurement
  intent, without general scan-plan mutation or automatic retune;
- local sequential executor boundary: run user-authored steps only after the
  read model proves useful but insufficient, without remote execution, resource
  arbitration, automatic retry, or write-back authority;
- links to parameter states and measurement records: record explicit references,
  without extracting a generic episode/step/context framework.

### Selected Reference Comparison

| Document | Use For |
| --- | --- |
| [`problem-briefs/selected-reference-comparison.md`](problem-briefs/selected-reference-comparison.md) | Problem framing for selected references, user marks, setup reality, objective comparison findings, and user-interpretation boundaries. |
| [`selected-reference-comparison-validation-plan.md`](selected-reference-comparison-validation-plan.md) | Fixture-validation boundaries for selected-reference context comparison. |
| [`selected-reference-comparison-validation-result.md`](selected-reference-comparison-validation-result.md) | Result of selected-reference context comparison fixtures, including the basic named-input fixture and declared code-context comparison fixture. |

Candidate next slices in this route should stay separate:

- deeper source-diff semantics: compare declared recorded-code observations
  more precisely, without Git analysis, semantic source review, or execution;
- restore/readiness comparison: compare declared restore or environment-readiness
  facts only after those facts are validated in the code-version route;
- setup-binding findings: report objective setup-binding comparison facts,
  without setup truth or parameter invalidation claims;
- parameter-state drift findings: report objective parameter-state differences,
  without making drift plots or causal scientific claims;
- import/export comparison preview: show preview compatibility across current,
  reference, imported, or exported records, without package writer or importer
  behavior;
- support-package review boundaries: decide recipient-safe review contents,
  without mixing redaction policy, export packaging, and comparison semantics
  into one validation slice.

## Promotion Discipline

Do not promote a validation result directly into shared architecture.

Before moving a concept into accepted schema, shared implementation, or
`docs/architecture/`, make sure there is:

- pressure from more than one validated slice;
- a concrete implementation need;
- explicit tests or contracts that would otherwise be duplicated;
- a narrower decision or ADR that names the ownership and what remains out of
  scope.
