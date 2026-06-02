# Measurement Records Route Index

## Status

Route index and navigation aid, not an ADR.

This document keeps Measurement Records discovery evidence, route decisions,
deferred questions, and reopen triggers in one place so
[`README.md`](../../README.md) can stay a short entrypoint. It does not replace
validation result documents, route decision consolidations, cross-slice
synthesis, or live engineering owners.

## Read First

For live implementation work, start from the engineering owner pointers below,
not this discovery route index.

Use these documents when interpreting prior Measurement Records discovery
evidence or deciding whether a discovery route should reopen:

| Document | Use For |
| --- | --- |
| [`policies/measurement-data-reference-boundary.md`](../../policies/measurement-data-reference-boundary.md) | Distinguish normalized primary data from external source references, attachments/artifacts, and previewable data items. |
| [`routes/measurement-records/import-source-decision.md`](import-source-decision.md) | Current import/source route decisions, deferred decisions, reopen triggers, and next-work guidance. |
| [`routes/measurement-records/legacy-brownfield-adoption-decision.md`](legacy-brownfield-adoption-decision.md) | Current post-run-first legacy adoption decisions, deferred decisions, reopen triggers, and stop rule. |
| [`policies/package-purpose-boundary.md`](../../policies/package-purpose-boundary.md) | Boundary between analysis/review packages, shared lab references, and future offline execution migration. |
| [`policies/artifact-preview-boundary.md`](../../policies/artifact-preview-boundary.md) | Boundary between arbitrary artifacts and declared previewable data items. |
| [`policies/complex-response-boundary.md`](../../policies/complex-response-boundary.md) | Boundary for complex-valued response metadata and derived component views. |
| [`slices/measurement-records/scan-data-shape-decision-summary.md`](../../slices/measurement-records/scan-data-shape-decision-summary.md) | Stop rule for scan/data-shape expansion and direction toward preview metadata consumers. |

Retired handoff discovery notes are not current starting points, but remain
useful historical context:

| Document | Use For |
| --- | --- |
| [`archive/measurement-records-handoff-route/README.md`](../../archive/measurement-records-handoff-route/README.md) | Retired handoff package route map and historical discovery synthesis; current handoff boundaries live in engineering prototype-boundary and module docs. |
| [`archive/measurement-records-handoff-route/decision.md`](../../archive/measurement-records-handoff-route/decision.md) | Retired handoff route decision closeout; preserved for historical deferrals, reopen triggers, and stop-rule context. |
| [`archive/measurement-records-handoff-route/contract-checklist.md`](../../archive/measurement-records-handoff-route/contract-checklist.md) | Historical route-local field categories and review checks for handoff package discovery slices. |

## Route Posture

This route index records discovery posture around recorded experiment data:
selection, export, import, handoff package use, storage writing, source
observation, and preview/read surfaces. It is evidence navigation, not the
owner of live Measurement Records implementation.

Prior import/source discovery closed around these accepted-for-now
separations, unless a named engineering workflow reopens them:

- legacy source references can be preserved for provenance and later
  file-level observation;
- adapter-normalized primary data is the route's current path to preview,
  copy, storage, package, SDK/table access, and plotting;
- normalized primary table reading became a route-local engineering prototype
  contract for already-provided bytes and created-record read-view validation;
  current API ownership lives in
  [`src/scopecat/measurement_records/README.md`](../../../../src/scopecat/measurement_records/README.md);
- existing-record append receipt records append evidence under an existing
  record, but it does not replace manifests, merge primary data, refresh read
  models, define lock identity, or accept crash recovery.

Prior legacy brownfield discovery closed around a post-run-first route:
external legacy execution can remain unchanged while Scopecat records declared
sidecar facts, reviews flexible locators, optionally observes an explicit
file-backed locator, and carries reviewed sidecar facts forward as
review/debug evidence. Live legacy storage behavior is now owned by engineering
prototype-boundary and module docs. Discovery still does not prove legacy file
observation, legacy code execution, legacy format parsing, reference repair, or
runner ownership. During-run event capture remains future-compatible but not
earned as runner ownership. See
[`legacy-brownfield-adoption-decision.md`](legacy-brownfield-adoption-decision.md).

Handoff package work moved from discovery route ownership into accepted
handoff prototype-boundary and module docs. Use retired discovery handoff docs
only for historical route synthesis. Shared lab references and offline
execution migration still require separate boundary work.

## Engineering Owner Pointers

This discovery route no longer owns active implementation sequencing. For live
Measurement Records work, start from
[`../../../engineering/workflow-validation-map.md`](../../../engineering/workflow-validation-map.md),
[`../../../engineering/capability-register.md`](../../../engineering/capability-register.md),
the relevant prototype-boundary note, and the live
[`src/scopecat/measurement_records/README.md`](../../../../src/scopecat/measurement_records/README.md).
For live handoff work, start from the engineering handoff boundary notes and
[`src/scopecat/handoff/README.md`](../../../../src/scopecat/handoff/README.md),
not the retired discovery handoff route.

Use this route index only to find discovery evidence, route decisions, deferred
questions, and reopen triggers.

Do not add another discovery import/source slice merely to restate that
external source references are not previewable primary data, that file-level
observation is not data-level observation, or that adapters own legacy parsing.

Do not add another discovery brownfield sidecar slice merely to restate
post-run-first adoption, flexible legacy locators, optional context links,
supporting evidence posture, file-level observation limits, review-evidence
receipt readback, or no-runner/no-import/no-write-back boundaries. New legacy
work should now attach to a named engineering workflow question before adding
more discovery evidence.

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
| [`normalized-primary-table-validation-result.md`](../../slices/measurement-records/normalized-primary-table-validation-result.md) | Historical validation evidence for the promoted route-local normalized primary CSV table contract over already-provided bytes. |
| [`adapter-authored-legacy-import-validation-result.md`](../../slices/measurement-records/adapter-authored-legacy-import-validation-result.md) | Normalized adapter-authored legacy import manifest candidate. |
| [`adapter-output-boundary-validation-result.md`](../../slices/measurement-records/adapter-output-boundary-validation-result.md) | File-shaped adapter-produced input boundary as transport pressure. |
| [`legacy-import-acceptance-validation-result.md`](../../slices/measurement-records/legacy-import-acceptance-validation-result.md) | Historical approved copy-into-new-record acceptance candidate; active new-record import is owned by durable Measurement Records import. |
| [`reference-only-legacy-import-validation-result.md`](../../slices/measurement-records/reference-only-legacy-import-validation-result.md) | Reference-only acceptance candidate for preserving external source references. |
| [`reference-only-source-observation-validation-result.md`](../../slices/measurement-records/reference-only-source-observation-validation-result.md) | File-level observation candidate for preserved external source references. |
| [`legacy-run-sidecar-manifest-validation-result.md`](../../slices/measurement-records/legacy-run-sidecar-manifest-validation-result.md) | Local review summary candidate for wrapping an externally executed legacy run with declared legacy source locators, optional context links, primary-data refs, supporting evidence refs, and lifecycle events. |
| [`legacy-locator-sufficiency-review-validation-result.md`](../../slices/measurement-records/legacy-locator-sufficiency-review-validation-result.md) | Review-only classifier for whether declared legacy locators are sufficient for human navigation without backend lookup, path parsing, file observation, import acceptance, storage mutation, or repair. |
| [`legacy-sidecar-post-run-review-validation-result.md`](../../slices/measurement-records/legacy-sidecar-post-run-review-validation-result.md) | Local post-run review projection over prior legacy sidecar and locator-review summaries without fresh observation, import acceptance, storage mutation, reference repair, parameter write-back, or GUI behavior. |
| [`legacy-sidecar-review-gui-state-validation-result.md`](../../slices/measurement-records/legacy-sidecar-review-gui-state-validation-result.md) | Passive GUI, CLI, or notebook-ready view-state projection over prior sidecar post-run review, exposing cards and action labels without action execution, backend lookup, file observation, import acceptance, storage mutation, repair, parameter write-back, measurement-validity decisions, or run blocking. |
| [`legacy-file-backed-locator-observation-validation-result.md`](../../slices/measurement-records/legacy-file-backed-locator-observation-validation-result.md) | Explicit file-level observation for one selected declared `legacy_path` locator under a caller-provided external root/path without backend lookup, parsing, preview verification, import acceptance, storage mutation, reference repair, parameter write-back, measurement-validity decisions, or GUI behavior. |
| [`legacy-locator-observation-review-bundle-validation-result.md`](../../slices/measurement-records/legacy-locator-observation-review-bundle-validation-result.md) | Local review composition over prior sidecar post-run review and optional prior file-backed locator observations without fresh observation, backend lookup, parsing, preview verification, import acceptance, storage mutation, reference repair, parameter write-back, measurement-validity decisions, or GUI behavior. |
| [`reviewed-legacy-sidecar-append-intent-validation-result.md`](../../slices/measurement-records/reviewed-legacy-sidecar-append-intent-validation-result.md) | Explicit operator-approved intent to append reviewed legacy sidecar and locator-observation facts later as review/debug evidence without storage mutation, record write, primary-data import, parsing, preview verification, repair, parameter write-back, measurement-validity decisions, or GUI behavior. |
| [`reviewed-legacy-sidecar-evidence-append-receipt-validation-result.md`](../../slices/measurement-records/reviewed-legacy-sidecar-evidence-append-receipt-validation-result.md) | Approved write of one review-evidence receipt under an existing measurement record without primary-data import, parsing, preview verification, repair, parameter write-back, measurement-validity decisions, manifest replacement, read-model refresh, or GUI behavior. |
| [`legacy-evidence-receipt-read-view-validation-result.md`](../../slices/measurement-records/legacy-evidence-receipt-read-view-validation-result.md) | Read-only view over declared legacy review-evidence receipt paths, surfacing receipt identity and findings without storage scan, mutation, primary-data read/import, parsing, preview verification, repair, parameter write-back, measurement-validity decisions, read-model refresh, or GUI behavior. |
| [`legacy-brownfield-adoption-backbone-validation-result.md`](../../slices/measurement-records/legacy-brownfield-adoption-backbone-validation-result.md) | Post-run-first composition over the legacy sidecar review and review-evidence receipt chain, validating identity/readback continuity while keeping during-run lifecycle support as future-compatible declared events rather than runner ownership. |
| [`legacy-calibration-handoff-parameter-state-bridge-validation-result.md`](../../slices/measurement-records/legacy-calibration-handoff-parameter-state-bridge-validation-result.md) | Explicit review bridge from a legacy sidecar adoption summary to calibration accepted-write handoff and parameter-state intake, preserving measurement/provenance continuity without legacy write-back, parameter-state storage mutation, hardware apply, or payload import. |
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
[`handoff.md`](../../../engineering/prototype-boundaries/handoff.md)
and the historical first candidate storage mutation boundary lives in
[`handoff-candidate-storage-acceptance.md`](../../../engineering/archive/handoff-candidate-storage-acceptance.md).
The historical storage/import requirements synthesis from before durable
measurement-record creation lives in
[`handoff-storage-import-requirements-synthesis.md`](../../../engineering/archive/handoff-storage-import-requirements-synthesis.md).
The active durable handoff import boundary lives in
[`handoff-durable-import-storage.md`](../../../engineering/prototype-boundaries/handoff-durable-import-storage.md).

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
