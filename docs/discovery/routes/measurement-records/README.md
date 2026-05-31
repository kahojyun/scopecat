# Measurement Records Route Index

## Status

Route index and navigation aid, not an ADR.

This document keeps Measurement Records discovery links and route ownership in
one place so [`README.md`](../../README.md) can stay a short entrypoint. It does not
replace validation result documents, route decision consolidations, or
cross-slice synthesis.

## Read First

Use these documents before adding new Measurement Records behavior:

| Document | Use For |
| --- | --- |
| [`policies/measurement-data-reference-boundary.md`](../../policies/measurement-data-reference-boundary.md) | Distinguish normalized primary data from external source references, attachments/artifacts, and previewable data items. |
| [`routes/measurement-records/import-source-decision.md`](import-source-decision.md) | Current import/source route decisions, deferred decisions, reopen triggers, and next-work guidance. |
| [`policies/package-purpose-boundary.md`](../../policies/package-purpose-boundary.md) | Boundary between analysis/review packages, shared lab references, and future offline execution migration. |
| [`policies/artifact-preview-boundary.md`](../../policies/artifact-preview-boundary.md) | Boundary between arbitrary artifacts and declared previewable data items. |
| [`policies/complex-response-boundary.md`](../../policies/complex-response-boundary.md) | Boundary for complex-valued response metadata and derived component views. |
| [`slices/measurement-records/scan-data-shape-decision-summary.md`](../../slices/measurement-records/scan-data-shape-decision-summary.md) | Stop rule for scan/data-shape expansion and direction toward preview metadata consumers. |

Retired handoff discovery notes are not current starting points, but remain
useful historical context:

| Document | Use For |
| --- | --- |
| [`routes/measurement-records/handoff/README.md`](handoff/README.md) | Retired handoff package route map and historical discovery synthesis; current handoff boundaries live in architecture and module docs. |
| [`routes/measurement-records/handoff/decision.md`](handoff/decision.md) | Retired handoff route decision closeout; preserved for historical deferrals, reopen triggers, and stop-rule context. |
| [`routes/measurement-records/handoff/contract-checklist.md`](handoff/contract-checklist.md) | Historical route-local field categories and review checks for handoff package discovery slices. |

## Route Posture

Measurement Records currently owns evidence around recorded experiment data:
selection, export, import, handoff package use, storage writing, source
observation, and preview/read surfaces. It does not own experiment-code
recording, environment sync, runtime readiness, execution, hardware control,
or final shared domain schemas.

Import/source work is currently closed around these accepted-for-now
separations:

- legacy source references can be preserved for provenance and later
  file-level observation;
- adapter-normalized primary data is the route's current path to preview,
  copy, storage, package, SDK/table access, and plotting;
- normalized primary table reading is the first shared data-level table
  contract, but it does not observe files, infer schemas, build plot series,
  or define dataframe behavior;
- existing-record append receipt records append evidence under an existing
  record, but it does not replace manifests, merge primary data, refresh read
  models, define lock identity, or accept crash recovery.

Handoff package work has moved from discovery route ownership into the accepted
handoff architecture and module docs. Use the retired discovery handoff docs
only for historical route synthesis. Shared lab references and offline
execution migration still require separate boundary work.

## Current Next Work

Prefer one of these only when the named workflow exists:

| Need | Next Boundary |
| --- | --- |
| Create durable measurement-record shells before writer/import integration | Start from [`architecture/measurement-records/creation-lifecycle-decision.md`](../../../architecture/measurement-records/creation-lifecycle-decision.md). |
| Import reviewed normalized primary data into durable storage | Start from [`architecture/handoff/durable-import-storage-decision.md`](../../../architecture/handoff/durable-import-storage-decision.md): create a new measurement record through the existing receipt/read-model pipeline. |
| Read or preview stored/package-local normalized data through one contract | Adopt [`slices/measurement-records/normalized-primary-table-validation-result.md`](../../slices/measurement-records/normalized-primary-table-validation-result.md) at that concrete consumer boundary. |
| Inspect a still-running durable record | Start from [`architecture/measurement-records/creation-lifecycle-decision.md`](../../../architecture/measurement-records/creation-lifecycle-decision.md): in-progress append receipts plus read-only running inspection. |
| Add durable storage editing beyond in-progress append receipts | Validate stronger existing-record update behavior: existing-record import/update, stale-lock cleanup, crash recovery, conflict policy, or canonical append visibility. |
| Accept adapter-produced input through a real workflow | Extend [`adapter-output-boundary-validation-result.md`](../../slices/measurement-records/adapter-output-boundary-validation-result.md) into a concrete transport, discovery, trust, and failure model. |
| Recover moved reference-only records | Validate reference repair/review without automatic path discovery by default. |
| Continue handoff package behavior | Start from [`architecture/handoff/engineering-prototype-promotion-decision.md`](../../../architecture/handoff/engineering-prototype-promotion-decision.md), [`architecture/handoff/durable-import-storage-decision.md`](../../../architecture/handoff/durable-import-storage-decision.md), and [`scopecat/handoff/README.md`](../../../../scopecat/handoff/README.md), not the retired discovery route. |

Do not add another import/source slice merely to restate that external source
references are not previewable primary data, that file-level observation is not
data-level observation, or that adapters own legacy parsing.

## Route Documents

### Problem And Boundary Framing

| Document | Use For |
| --- | --- |
| [`problem-briefs/selected-run-handoff.md`](../../problem-briefs/selected-run-handoff.md) | Problem framing for selected-run handoff and export pressure. |
| [`problem-briefs/measurement-record-boundary.md`](../../problem-briefs/measurement-record-boundary.md) | Boundary pressure around primary measurement data, context, attachments, and artifacts. |
| [`selected-run-handoff-spike-summary.md`](../../slices/measurement-records/selected-run-handoff-spike-summary.md) | Narrow spike summary before preview-ready export consolidation. |
| [`selected-measurement-export-decision-summary.md`](../../slices/measurement-records/selected-measurement-export-decision-summary.md) | Decision-ready discovery summary for preview-ready selected measurement export. |
| [`preview-ready-selected-measurement-export-plan.md`](../../slices/measurement-records/preview-ready-selected-measurement-export-plan.md) | Planning boundary for the source/metadata-first export slice. |
| [`preview-ready-selected-measurement-export-implementation-plan.md`](../../slices/measurement-records/preview-ready-selected-measurement-export-implementation-plan.md) | Code-facing plan for the pure selected measurement export summary builder. |
| [`policies/external-file-reference.md`](../../policies/external-file-reference.md) | Candidate policy vocabulary for external files, latest state, observed file state, and non-backup boundaries. |
| [`storage-transition-export-fixture.md`](../../slices/measurement-records/storage-transition-export-fixture.md) | Fixture note for managed storage, external references, source identity, and export materialization pressure. |
| [`storage-transition-export-validation-result.md`](../../slices/measurement-records/storage-transition-export-validation-result.md) | Result of the storage-transition fixture and domain review. |

### Export, Import, Storage, And Source Observation

| Document | Use For |
| --- | --- |
| [`preview-ready-selected-measurement-export-validation-result.md`](../../slices/measurement-records/preview-ready-selected-measurement-export-validation-result.md) | First implementation-shaped selected measurement export candidate. |
| [`measurement-record-import-preview-validation-result.md`](../../slices/measurement-records/measurement-record-import-preview-validation-result.md) | Side-effect-free incoming-record import preview candidate. |
| [`normalized-primary-table-validation-result.md`](../../slices/measurement-records/normalized-primary-table-validation-result.md) | Normalized primary CSV table read candidate over already-provided bytes. |
| [`adapter-authored-legacy-import-validation-result.md`](../../slices/measurement-records/adapter-authored-legacy-import-validation-result.md) | Normalized adapter-authored legacy import manifest candidate. |
| [`adapter-output-boundary-validation-result.md`](../../slices/measurement-records/adapter-output-boundary-validation-result.md) | File-shaped adapter-produced input boundary as transport pressure. |
| [`legacy-import-acceptance-validation-result.md`](../../slices/measurement-records/legacy-import-acceptance-validation-result.md) | Historical approved copy-into-new-record acceptance candidate; active new-record import is owned by durable Measurement Records import. |
| [`reference-only-legacy-import-validation-result.md`](../../slices/measurement-records/reference-only-legacy-import-validation-result.md) | Reference-only acceptance candidate for preserving external source references. |
| [`reference-only-source-observation-validation-result.md`](../../slices/measurement-records/reference-only-source-observation-validation-result.md) | File-level observation candidate for preserved external source references. |
| [`legacy-run-sidecar-manifest-validation-result.md`](../../slices/measurement-records/legacy-run-sidecar-manifest-validation-result.md) | Local review summary candidate for wrapping an externally executed legacy run with declared legacy source locators, optional context links, primary-data refs, supporting evidence refs, and lifecycle events. |
| [`legacy-locator-sufficiency-review-validation-result.md`](../../slices/measurement-records/legacy-locator-sufficiency-review-validation-result.md) | Review-only classifier for whether declared legacy locators are sufficient for human navigation without backend lookup, path parsing, file observation, import acceptance, storage mutation, or repair. |
| [`legacy-sidecar-post-run-review-validation-result.md`](../../slices/measurement-records/legacy-sidecar-post-run-review-validation-result.md) | Local post-run review projection over prior legacy sidecar and locator-review summaries without fresh observation, import acceptance, storage mutation, reference repair, parameter write-back, or GUI behavior. |
| [`new-run-measurement-writer-validation-result.md`](../../slices/measurement-records/new-run-measurement-writer-validation-result.md) | Side-effect-free writer-event summary candidate. |
| [`measurement-storage-writer-validation-result.md`](../../slices/measurement-records/measurement-storage-writer-validation-result.md) | Approved append-only storage writer candidate for new records. |
| [`existing-record-update-validation-result.md`](../../slices/measurement-records/existing-record-update-validation-result.md) | Approved existing-record append update candidate. |
| [`measurement-source-observation-validation-result.md`](../../slices/measurement-records/measurement-source-observation-validation-result.md) | Read-only observation candidate for normalized primary data under storage. |
| [`derived-artifact-source-links-validation-result.md`](../../slices/measurement-records/derived-artifact-source-links-validation-result.md) | Explicit derived-artifact source-link candidate. |

### Running Measurement And Shape Pressure

| Document | Use For |
| --- | --- |
| [`problem-briefs/running-measurement-inspection.md`](../../problem-briefs/running-measurement-inspection.md) | Problem framing for inspecting already-recorded data from still-running measurements. |
| [`running-measurement-inspection-validation-plan.md`](../../slices/measurement-records/running-measurement-inspection-validation-plan.md) | First fixture-validation boundary for running inspection. |
| [`running-measurement-inspection-validation-result.md`](../../slices/measurement-records/running-measurement-inspection-validation-result.md) | Running-inspection implementation candidate. |
| [`../../spikes/scan_data_shapes/README.md`](../../../../spikes/scan_data_shapes/README.md) | Spike boundary for declared scan/data-shape fixture generation. |
| [`scan-data-shape-validation-result.md`](../../slices/measurement-records/scan-data-shape-validation-result.md) | Checkpoint for declared scan/data-shape fixture pressure. |
| [`../../tests/fixtures/scan_data_shapes/`](../../../../tests/fixtures/scan_data_shapes) | Repository-safe scan/data-shape fixtures. |

### Handoff Package Route

These rows are historical discovery evidence. Current accepted implementation
boundaries live in
[`engineering-prototype-promotion-decision.md`](../../../architecture/handoff/engineering-prototype-promotion-decision.md)
and the historical first candidate storage mutation boundary lives in
[`storage-acceptance-decision.md`](../../../architecture/handoff/storage-acceptance-decision.md).
The historical storage/import requirements synthesis from before durable
measurement-record creation lives in
[`storage-import-requirements-synthesis.md`](../../../architecture/handoff/storage-import-requirements-synthesis.md).
The active durable handoff import boundary lives in
[`durable-import-storage-decision.md`](../../../architecture/handoff/durable-import-storage-decision.md).

| Document | Use For |
| --- | --- |
| [`contents-preview-validation-result.md`](../../slices/measurement-records/handoff/contents-preview-validation-result.md) | Manifest-only orientation before read-only package use. |
| [`opener-validation-result.md`](../../slices/measurement-records/handoff/opener-validation-result.md) | Read-only open for directory-shaped Scopecat-authored packages. |
| [`read-view-validation-result.md`](../../slices/measurement-records/handoff/read-view-validation-result.md) | Reader-facing object view over the read-only opener. |
| [`sdk-view-model-validation-result.md`](../../slices/measurement-records/handoff/sdk-view-model-validation-result.md) | Thin Python-facing SDK view-model candidate. |
| [`sdk-ergonomics-spike-validation-result.md`](../../slices/measurement-records/handoff/sdk-ergonomics-spike-validation-result.md) | Notebook-style fixture pressure over the SDK view model. |
| [`preview-shape-view-validation-result.md`](../../slices/measurement-records/handoff/preview-shape-view-validation-result.md) | Declared preview plot/view projection over read-only handoff packages. |
| [`preview-consumption-validation-result.md`](../../slices/measurement-records/handoff/preview-consumption-validation-result.md) | Preview-aware local consumption composition. |
| [`visual-review-validation-result.md`](../../slices/measurement-records/handoff/visual-review-validation-result.md) | Plot-first local review view model. |
| [`gui-view-state-validation-result.md`](../../slices/measurement-records/handoff/gui-view-state-validation-result.md) | Local GUI-ready view-state projection. |
| [`visual-artifact-validation-result.md`](../../slices/measurement-records/handoff/visual-artifact-validation-result.md) | Local static HTML review artifact candidate. |
| [`inspection-workflow-validation-result.md`](../../slices/measurement-records/handoff/inspection-workflow-validation-result.md) | Receiving-side local inspection workflow. |
| [`route-pressure-validation-result.md`](../../slices/measurement-records/handoff/route-pressure-validation-result.md) | Richer repository-safe route-pressure fixtures. |
| [`acceptance-validation-result.md`](../../slices/measurement-records/handoff/acceptance-validation-result.md) | Approved receiving-side storage acceptance candidate. |
| [`integrity-observation-validation-result.md`](../../slices/measurement-records/handoff/integrity-observation-validation-result.md) | Read-only package-local integrity observation candidate. |
| [`receiving-workflow-validation-result.md`](../../slices/measurement-records/handoff/receiving-workflow-validation-result.md) | Receiving-side workflow composition over inspection, integrity observation, and acceptance. |
| [`writer-validation-result.md`](../../slices/measurement-records/handoff/writer-validation-result.md) | Approved directory-shaped handoff package writer candidate. |
| [`round-trip-validation-result.md`](../../slices/measurement-records/handoff/round-trip-validation-result.md) | Writer-to-reader compatibility candidate. |

### Support Candidates

| Document | Use For |
| --- | --- |
| [`contract-primitives-validation-result.md`](../../slices/support/contract-primitives-validation-result.md) | Narrow shared validation helpers for repeated low-level checks. |
| [`filesystem-mutation-helpers-validation-result.md`](../../slices/support/filesystem-mutation-helpers-validation-result.md) | Narrow no-overwrite filesystem mutation helpers. |
| [`../../implementation_candidates/handoff_package_contracts/`](../../../../implementation_candidates/handoff_package_contracts) | Route-local helper contracts shared by handoff package candidates. |
| [`../../implementation_candidates/measurement_record_handoff_flow/`](../../../../implementation_candidates/measurement_record_handoff_flow) | First import-to-handoff composition candidate. |

Context-shaped work such as recorded analysis choices and handoff context
should use [`synthesis/measurement-context-backlog.md`](../../synthesis/measurement-context-backlog.md)
unless the slice is about primary measurement data or direct
artifact-to-measurement source-link boundaries.
