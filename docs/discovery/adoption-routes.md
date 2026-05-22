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

Evidence claims live in
[`../evidence/evidence-register.md`](../evidence/evidence-register.md).
Problem framing lives in
[`problem-briefs/README.md`](problem-briefs/README.md).

Current cross-slice comparison lives in
[`cross-slice-synthesis.md`](cross-slice-synthesis.md).

## Route Selection Rule

Prefer routes cut from verified current-state obligations and validated slices,
not from clean architecture categories or future capabilities. A route can stay
provisional when the current-state pain is clear and at least one fixture,
validation result, or implementation-shaped slice shows how users might adopt
part of it.

Do not split one route only because the validation work is sliced. Do split
routes when users adopt a different durable object, make a different workflow
commitment, or cross a materially different authority boundary.

## Routes

| Adoption route | Current-state pressure | Behavior change | Validated slices | Candidate next slices |
| --- | --- | --- | --- | --- |
| Use measurement records for selection, inspection, handoff, and traceability | Data Vault-style IDs, session paths, primary data, partial rows, companion artifacts, selected IDs, handoff packages, local paths, derived arrays, figures, fits, reports, and missing-context warnings. | Users treat measurement records as the anchor for source data, recorded context, selection, preview, export/import, running inspection, and later analysis traceability instead of reconstructing folders and notebooks manually. | Selected measurement export; storage-transition export; running measurement inspection. | Import preview, offline legacy-record import, derived-analysis trace to source measurements and recorded analysis choices, and new-run measurement writer semantics. |
| Manage parameter state and reviewed writes | Active parameter files, run-adjacent snapshots, copied seeds, dated variants, bad states, trust/readiness gaps, direct JSON writes, reset/diff pressure, and run links. | Users recover, compare, edit, commit, and review calibrated parameter states without treating mutable files as the only authority or letting Scopecat silently decide hardware mutation. | Parameter state management. | Reviewable parameter-write records, compatibility JSON writer, drift views, and calibration-step links to selected parameter states. |
| Select experiment code context and captured versions | Copied folders, notebooks, backup trees, entrypoint ambiguity, helper roots, local dependency notes, selected references, last-working code, and cross-computer code drift. | Users identify the code context that mattered for a measurement, calibration step, analysis, or handoff, then capture or restore selected versions without adopting Git-facing workflow up front. | Experiment code selection. | Managed captured-version storage, selected-version comparison, environment-readiness records, and later materialization or loading of selected versions. |
| Track setup bindings and run-start context | Registry variants, wiring workbooks, generated chip/line state, LO/readout groupings, station references, measurement run-start inputs, and parameter-retuning pressure after binding changes. | Users record which sample/cooldown binding mapped logical entities to physical resources for a measurement while keeping setup truth, parameter state, and hardware control separate. | Setup binding. | Setup-binding comparison, setup import/validation reports, run-start named input snapshots, and selected-reference setup findings. |
| Continue calibration work with reviewable state | Sequential scans, grouped calibration intent, fit previews, review gates, skipped or blocked steps, interruptions, continuation, proposed writes, local sequential execution, and outcome records. | Users run or review user-authored calibration work with durable step state, requested next actions, and explicit proposed writes instead of relying on notebook cell state and hidden file mutation. | Calibration work continuation. | Local sequential executor boundary, review/resume UX, calibration-write review, selected-group remeasurement, and links to parameter states and measurement records. |
| Compare selected reference context | Selected current/reference records, user marks such as last-working or notable, setup reality, parameter and setup context, preview compatibility, support packages, and control-PC safety. | Users compare recorded current context against a selected reference and see objective changed, missing, unverified, redacted, unlinked, same-observed, or not-compared findings without Scopecat claiming equivalence, setup truth, or reference goodness. | Selected reference comparison. | Code-version comparison, setup-binding findings, parameter-state drift findings, import/export comparison preview, and support-package review boundaries. |

## Shared Constraints

Cross-machine value should first be tested as portable records, export/import,
handoff packages, existing shared-storage discovery or references, and
openability checks. Shared storage may help when a lab already has it, but
remote execution, central services, sync, leases, and resource arbitration are
separate decisions.

Local batch execution may be unattended when the user has declared the steps,
order, review gates, and stop/failure policy. Open-ended autonomy, remote
execution, resource arbitration, Scopecat-decided mutation, and
Scopecat-decided write-back remain separate decisions.

Cross-computer code movement should first be tested as explicit selection,
capture, and recovery. Publish/pull, automatic sync, Git hosting, deployment
management, and managed load-selected-version execution remain later
validation questions.

General runtime ownership, managed execution, code registries, automatic
version management, proposal workflows, and similar solution names should stay
out of this file unless a validation result makes them the next route-level
question.

High-bar runtime expansion is not permanently excluded. Owning drivers, scan
framework behavior, hardware-control runtime, service lifecycle, concurrency,
or resource arbitration should be treated as later expansion pressure that needs
separate evidence and decision records, not as an early adoption assumption.
If validated later, these capabilities should remain optional adoption paths or
backend choices rather than mandatory replacements for existing lab systems.
