# Adoption Routes

## Status

Discovery adoption evidence.

This document preserves evidence-backed adoption-route framing from discovery.
It is not the current product adoption owner. Use
[`../../product/adoption-model.md`](../../product/adoption-model.md) for the
current adoption model.

## Purpose

Preserve historical discovery framing for durable user-value paths that connect
multiple validation slices. These routes explain why earlier validation work
was grouped the way it was; they no longer own current adoption strategy.

A route is different from a validation slice:

- a route names the workflow users might progressively adopt;
- a validation slice tests one small question inside that route;
- a problem brief owns the evidence-backed failure framing;
- an implementation plan or result owns prototype details.

## Related Owners

| Owner | Use For |
| --- | --- |
| [`../../evidence/evidence-register.md`](../../evidence/evidence-register.md) | Stable evidence claims and source coverage. |
| [`problem-briefs/README.md`](../problem-briefs/README.md) | Evidence-backed user-facing failure cases. |
| [`README.md#validation-slices`](../README.md#validation-slices) | Discovery validation slices historically grouped under these routes. |
| [`../synthesis/cross-slice.md`](../synthesis/cross-slice.md) | Recurring candidate concepts across validated slices. |
| [`../synthesis/measurement-context-backlog.md`](../synthesis/measurement-context-backlog.md) | Shared discovery backlog for context-shaped validation work across routes. |
| [`../synthesis/shared-model-extraction-deferral.md`](../synthesis/shared-model-extraction-deferral.md) | Why shared domain models are still deferred. |
| [`../../product/direction.md`](../../product/direction.md) | Current product direction, ownership assumptions, non-goals, and expansion strategy. |
| [`../../product/adoption-model.md`](../../product/adoption-model.md) | Current product adoption paths and brownfield migration boundaries. |

## Route Selection

Prefer routes cut from verified current-state obligations and validated slices.
A route can stay provisional when the current-state pain is clear and at least
one fixture, validation result, or implementation-shaped slice shows how users
might adopt part of it.

Split routes when users adopt a different durable object, make a different
workflow commitment, or cross a materially different authority boundary.

## Historical Discovery Adoption Evidence

| Historical route | Durable object | Discovery pressure | Evidence-backed behavior change | Historical evidence / current owner |
| --- | --- | --- | --- | --- |
| Use measurement records for selection, inspection, handoff, and traceability | Measurement record and linked context. | Data Vault-style IDs, session paths, primary data, partial rows, companion artifacts, selected IDs, handoff packages, local paths, derived arrays, figures, fits, reports, and missing-context warnings. | Users treat measurement records as the anchor for source data, recorded context, selection, preview, export/import, running inspection, and later analysis traceability instead of reconstructing folders and notebooks manually. | [`measurement-records/README.md`](measurement-records/README.md), [`../problem-briefs/selected-run-handoff.md`](../problem-briefs/selected-run-handoff.md), [`../problem-briefs/measurement-record-boundary.md`](../problem-briefs/measurement-record-boundary.md), [`../problem-briefs/running-measurement-inspection.md`](../problem-briefs/running-measurement-inspection.md). |
| Manage parameter state and reviewed writes | Parameter state lineage, reviewed import, storage read/write, and reviewable change. | Active parameter files, run-adjacent snapshots, copied seeds, dated variants, bad states, trust/readiness gaps, direct JSON/XLSX-derived values, reset/diff pressure, and run-preparation links. | Users recover, compare, import through adapters, commit, store, read, and review calibrated parameter states without treating mutable files as the only authority or letting Scopecat silently decide hardware mutation. | [`parameter-state/README.md`](parameter-state/README.md), [`../../engineering/prototype-boundaries/parameter-state.md`](../../engineering/prototype-boundaries/parameter-state.md), [`../problem-briefs/parameter-state-management.md`](../problem-briefs/parameter-state-management.md). |
| Record experiment code versions | Run/step code context defining a code snapshot record. | Copied folders, notebooks, backup trees, entrypoint ambiguity, helper roots, local dependency notes, declared environment files, selected references, last-working code, and cross-computer code drift. | Users preserve the code and declared environment context associated with a measurement, calibration step, analysis, or handoff, then later select, compare, materialize, or restore point-in-time code versions without adopting Git-facing workflow up front. | [`experiment-code/README.md`](experiment-code/README.md), [`../problem-briefs/experiment-code-recording.md`](../problem-briefs/experiment-code-recording.md), [`../policies/managed-experiment-code-posture.md`](../policies/managed-experiment-code-posture.md), [`../slices/experiment-code/experiment-code-recording-next-boundary.md`](../slices/experiment-code/experiment-code-recording-next-boundary.md). |
| Track setup bindings and run-start context | Setup binding snapshot and named run-start input. | Registry variants, wiring workbooks, generated chip/line state, LO/readout groupings, station references, measurement run-start inputs, and parameter-retuning pressure after binding changes. | Users record which sample/cooldown binding mapped logical entities to physical resources for a measurement while keeping setup truth, parameter state, and hardware control separate. | [`setup-binding/README.md`](setup-binding/README.md), [`../problem-briefs/setup-binding.md`](../problem-briefs/setup-binding.md). |
| Continue calibration work with reviewable state | Calibration episode, step state, proposed write, and calibration-derived parameter-state context. | Sequential scans, grouped calibration intent, fit previews, review gates, skipped or blocked steps, interruptions, continuation, proposed writes, declared execution/outcome records, and later measurement context that depends on accepted calibration writes. | Users run or review user-authored calibration work while Scopecat records durable step state, requested next actions, explicit proposed writes, and a reviewed handoff into later measurement context instead of relying on notebook cell state and hidden file mutation. | [`calibration-continuation/README.md`](calibration-continuation/README.md), [`../problem-briefs/calibration-work-continuation.md`](../problem-briefs/calibration-work-continuation.md), [`../slices/calibration/calibration-derived-parameter-state-measurement-context-validation-result.md`](../slices/calibration/calibration-derived-parameter-state-measurement-context-validation-result.md), [`../../product/direction.md#ownership-assumptions`](../../product/direction.md#ownership-assumptions). |
| Compare selected reference context | Selected reference and objective comparison findings. | Selected current/reference records, user marks such as last-working or notable, setup reality, parameter and setup context, preview compatibility, support packages, and control-PC safety. | Users compare recorded current context against a selected reference and see objective changed, missing, unverified, redacted, unlinked, same-observed, or not-compared findings without Scopecat claiming equivalence, setup truth, or reference goodness. | [`../problem-briefs/selected-reference-comparison.md`](../problem-briefs/selected-reference-comparison.md), [`../slices/selected-reference/selected-reference-comparison-validation-result.md`](../slices/selected-reference/selected-reference-comparison-validation-result.md). |
