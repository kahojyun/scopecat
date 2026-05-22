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
Validation-slice navigation lives in [`README.md`](README.md).
Product ownership and expansion posture live in
[`../strategy/product-direction.md`](../strategy/product-direction.md).

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

| Adoption route | Durable object | Current-state pressure | Behavior change | Route boundary |
| --- | --- | --- | --- | --- |
| Use measurement records for selection, inspection, handoff, and traceability | Measurement record and linked context. | Data Vault-style IDs, session paths, primary data, partial rows, companion artifacts, selected IDs, handoff packages, local paths, derived arrays, figures, fits, reports, and missing-context warnings. | Users treat measurement records as the anchor for source data, recorded context, selection, preview, export/import, running inspection, and later analysis traceability instead of reconstructing folders and notebooks manually. | Does not imply final storage identity, package format, importer, reader API, rendered plotting, recursive analysis DAG, or report generation. |
| Manage parameter state and reviewed writes | Parameter state lineage and reviewable change. | Active parameter files, run-adjacent snapshots, copied seeds, dated variants, bad states, trust/readiness gaps, direct JSON writes, reset/diff pressure, and run links. | Users recover, compare, edit, commit, and review calibrated parameter states without treating mutable files as the only authority or letting Scopecat silently decide hardware mutation. | Does not imply hardware state truth, rollback policy, automatic write-back, universal parameter schema, or Scopecat-decided mutation. |
| Select experiment code context and captured versions | Selected code context and captured-version candidate. | Copied folders, notebooks, backup trees, entrypoint ambiguity, helper roots, local dependency notes, selected references, last-working code, and cross-computer code drift. | Users identify the code context that mattered for a measurement, calibration step, analysis, or handoff, then capture or restore selected versions without adopting Git-facing workflow up front. | Does not imply Git hosting, default record-all tracking, package/dependency closure, environment ownership, code execution, sync, merge, or workflow-DAG semantics. |
| Track setup bindings and run-start context | Setup binding snapshot and named run-start input. | Registry variants, wiring workbooks, generated chip/line state, LO/readout groupings, station references, measurement run-start inputs, and parameter-retuning pressure after binding changes. | Users record which sample/cooldown binding mapped logical entities to physical resources for a measurement while keeping setup truth, parameter state, and hardware control separate. | Does not imply software-proof of physical wiring, authoritative setup truth, universal topology schema, device control, or a shared state model with parameter state. |
| Continue calibration work with reviewable state | Calibration episode, step state, and proposed write. | Sequential scans, grouped calibration intent, fit previews, review gates, skipped or blocked steps, interruptions, continuation, proposed writes, local sequential execution, and outcome records. | Users run or review user-authored calibration work with durable step state, requested next actions, and explicit proposed writes instead of relying on notebook cell state and hidden file mutation. | Does not imply scheduler, remote execution, resource arbitration, automatic retry, autonomous calibration, or Scopecat-decided write-back. |
| Compare selected reference context | Selected reference and objective comparison findings. | Selected current/reference records, user marks such as last-working or notable, setup reality, parameter and setup context, preview compatibility, support packages, and control-PC safety. | Users compare recorded current context against a selected reference and see objective changed, missing, unverified, redacted, unlinked, same-observed, or not-compared findings without Scopecat claiming equivalence, setup truth, or reference goodness. | Does not imply equivalence scoring, cause attribution, reference-goodness authority, rollback, scientific conclusion support, or a comparison engine. |

## Placement Boundaries

Do not use this file as a validation index. Keep current validated slices and
candidate next slices in [`README.md`](README.md), grouped by route.

Do not use this file as a shared model or architecture owner. Recurring concepts
and not-yet-earned shared schemas live in
[`cross-slice-synthesis.md`](cross-slice-synthesis.md) and
[`shared-model-extraction-deferral.md`](shared-model-extraction-deferral.md)
until a narrower decision promotes them.

Do not add solution-shaped routes such as central storage, sync, scheduler,
runtime, code registry, package manager, comparison engine, or driver framework
unless validated user workflow shows that adopting that solution boundary is
itself the durable behavior change. Product-wide ownership assumptions and
future expansion posture belong in
[`../strategy/product-direction.md`](../strategy/product-direction.md).
