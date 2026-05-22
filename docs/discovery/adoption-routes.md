# Adoption Routes

## Status

Provisional discovery owner.

This document names evidence-backed adoption routes. Routes are not accepted
product scope, implementation order, architecture, or a validation backlog.

## Purpose

Name the durable user-value paths that can connect multiple validation slices.
An adoption route should be broad enough to describe a behavior change in the
lab, but narrow enough to stay grounded in observed current-state pressure and
validated discovery work.

A route is different from a validation slice:

- a route names the workflow users might progressively adopt;
- a validation slice tests one small question inside that route;
- a problem brief owns the evidence-backed failure framing;
- an implementation plan or result owns prototype details.

## Related Owners

| Owner | Use For |
| --- | --- |
| [`../evidence/evidence-register.md`](../evidence/evidence-register.md) | Stable evidence claims and source posture. |
| [`problem-briefs/README.md`](problem-briefs/README.md) | Evidence-backed user-facing failure cases. |
| [`README.md#validation-slices`](README.md#validation-slices) | Current validation slices grouped under these routes. |
| [`cross-slice-synthesis.md`](cross-slice-synthesis.md) | Recurring candidate concepts across validated slices. |
| [`shared-model-extraction-deferral.md`](shared-model-extraction-deferral.md) | Why shared domain models are still deferred. |
| [`../strategy/product-direction.md`](../strategy/product-direction.md) | Product direction, ownership assumptions, non-goals, and expansion posture. |

## Route Selection

Prefer routes cut from verified current-state obligations and validated slices.
A route can stay provisional when the current-state pain is clear and at least
one fixture, validation result, or implementation-shaped slice shows how users
might adopt part of it.

Split routes when users adopt a different durable object, make a different
workflow commitment, or cross a materially different authority boundary.

## Routes

| Adoption route | Durable object | Current-state pressure | Behavior change | Read Next |
| --- | --- | --- | --- | --- |
| Use measurement records for selection, inspection, handoff, and traceability | Measurement record and linked context. | Data Vault-style IDs, session paths, primary data, partial rows, companion artifacts, selected IDs, handoff packages, local paths, derived arrays, figures, fits, reports, and missing-context warnings. | Users treat measurement records as the anchor for source data, recorded context, selection, preview, export/import, running inspection, and later analysis traceability instead of reconstructing folders and notebooks manually. | [`README.md#measurement-records`](README.md#measurement-records), [`problem-briefs/selected-run-handoff.md`](problem-briefs/selected-run-handoff.md), [`problem-briefs/measurement-record-boundary.md`](problem-briefs/measurement-record-boundary.md), [`problem-briefs/running-measurement-inspection.md`](problem-briefs/running-measurement-inspection.md). |
| Manage parameter state and reviewed writes | Parameter state lineage and reviewable change. | Active parameter files, run-adjacent snapshots, copied seeds, dated variants, bad states, trust/readiness gaps, direct JSON writes, reset/diff pressure, and run links. | Users recover, compare, edit, commit, and review calibrated parameter states without treating mutable files as the only authority or letting Scopecat silently decide hardware mutation. | [`README.md#parameter-state`](README.md#parameter-state), [`problem-briefs/parameter-state-management.md`](problem-briefs/parameter-state-management.md), [`parameter-state-management-validation-result.md`](parameter-state-management-validation-result.md). |
| Record experiment code versions | Run/step code context defining a code snapshot record. | Copied folders, notebooks, backup trees, entrypoint ambiguity, helper roots, local dependency notes, selected references, last-working code, and cross-computer code drift. | Users preserve the code context associated with a measurement, calibration step, analysis, or handoff, then later select, compare, materialize, or restore point-in-time code versions without adopting Git-facing workflow up front. | [`README.md#experiment-code-context`](README.md#experiment-code-context), [`problem-briefs/experiment-code-recording.md`](problem-briefs/experiment-code-recording.md), [`managed-experiment-code-posture.md`](managed-experiment-code-posture.md), [`experiment-code-recording-next-boundary.md`](experiment-code-recording-next-boundary.md). |
| Track setup bindings and run-start context | Setup binding snapshot and named run-start input. | Registry variants, wiring workbooks, generated chip/line state, LO/readout groupings, station references, measurement run-start inputs, and parameter-retuning pressure after binding changes. | Users record which sample/cooldown binding mapped logical entities to physical resources for a measurement while keeping setup truth, parameter state, and hardware control separate. | [`README.md#setup-binding`](README.md#setup-binding), [`problem-briefs/setup-binding.md`](problem-briefs/setup-binding.md), [`setup-binding-validation-result.md`](setup-binding-validation-result.md). |
| Continue calibration work with reviewable state | Calibration episode, step state, and proposed write. | Sequential scans, grouped calibration intent, fit previews, review gates, skipped or blocked steps, interruptions, continuation, proposed writes, local sequential execution, and outcome records. | Users run or review user-authored calibration work with durable step state, requested next actions, and explicit proposed writes instead of relying on notebook cell state and hidden file mutation. | [`README.md#calibration-continuation`](README.md#calibration-continuation), [`problem-briefs/calibration-work-continuation.md`](problem-briefs/calibration-work-continuation.md), [`calibration-work-continuation-validation-result.md`](calibration-work-continuation-validation-result.md), [`../strategy/product-direction.md#ownership-assumptions`](../strategy/product-direction.md#ownership-assumptions). |
| Compare selected reference context | Selected reference and objective comparison findings. | Selected current/reference records, user marks such as last-working or notable, setup reality, parameter and setup context, preview compatibility, support packages, and control-PC safety. | Users compare recorded current context against a selected reference and see objective changed, missing, unverified, redacted, unlinked, same-observed, or not-compared findings without Scopecat claiming equivalence, setup truth, or reference goodness. | [`README.md#selected-reference-comparison`](README.md#selected-reference-comparison), [`problem-briefs/selected-reference-comparison.md`](problem-briefs/selected-reference-comparison.md), [`selected-reference-comparison-validation-result.md`](selected-reference-comparison-validation-result.md). |
