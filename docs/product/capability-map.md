# Capability Map

## Status

Current product capability map.

## Purpose

Track Scopecat product capabilities and their maturity. This is a product
planning document, not an implementation inventory. A capability may support
multiple workflows and may be implemented by one or more modules.

Use this document with:

- [`adoption-model.md`](adoption-model.md) for user adoption paths and
  brownfield boundaries;
- [`../engineering/workflow-validation-map.md`](../engineering/workflow-validation-map.md)
  for workflow seams and next validation questions;
- [`../engineering/implementation-register.md`](../engineering/implementation-register.md)
  for live implementation owners and their detailed module/boundary docs.

## Capability Map

| Capability | Maturity | Product Boundary | Evidence Owner | Open Advancement Questions |
| --- | --- | --- | --- | --- |
| Measurement Records | Engineering prototype | Stores declared measurement facts and reviewed normalized data under a caller-provided storage root. Legacy run storage records declared external-run facts and optional converted primary data without requiring immediate legacy-system replacement. | [`../engineering/implementation-register.md`](../engineering/implementation-register.md), [`../engineering/prototype-boundaries/measurement-records-creation-lifecycle.md`](../engineering/prototype-boundaries/measurement-records-creation-lifecycle.md), [`../engineering/prototype-boundaries/measurement-records-legacy-run-storage.md`](../engineering/prototype-boundaries/measurement-records-legacy-run-storage.md) | Decide whether selected stored measurement export, existing-record update/import, running measurement lifecycle, or storage schema readiness is the next vertical-slice pressure. |
| Handoff Packages | Engineering prototype | Writes, opens, previews, gates, plans, and imports Scopecat-authored directory packages through Measurement Records durable import. | [`../engineering/implementation-register.md`](../engineering/implementation-register.md), [`../engineering/prototype-boundaries/handoff.md`](../engineering/prototype-boundaries/handoff.md), [`../engineering/prototype-boundaries/handoff-durable-import-storage.md`](../engineering/prototype-boundaries/handoff-durable-import-storage.md) | Validate selected stored Measurement Record to single-measurement handoff package export; decide later trust/authenticity, batch receiving, archive format, and linked-context payload import questions. |
| Parameter State Review | Engineering prototype | Owns adapter-authored previews, reviewed storage, manifest/receipt read views, source-agnostic projections, selection context, and route-local pre-run review-chain consumption. | [`../engineering/implementation-register.md`](../engineering/implementation-register.md), [`../engineering/prototype-boundaries/parameter-state.md`](../engineering/prototype-boundaries/parameter-state.md) | Decide whether compatibility-file writing, hardware apply, catalog discovery, automatic run start, or a shared parameter/run-context schema is justified by a workflow. |
| Environment Operation | Engineering prototype | Executes approved `uv sync` intent through a bounded route-local path, produces typed result/review objects, and can run a bounded interpreter fact probe. | [`../engineering/implementation-register.md`](../engineering/implementation-register.md), [`../engineering/prototype-boundaries/environment-operation.md`](../engineering/prototype-boundaries/environment-operation.md) | Decide whether runtime readiness, manifest integration, manager expansion, execution hardening, or GUI/runtime monitoring is the next validated product need. |
| Experiment Code Context | Discovery / validation evidence | No promoted implementation owner yet. Discovery evidence supports explicit code context records, include policy, managed version pressure, and materialization pressure. | [`../discovery/routes/experiment-code/README.md`](../discovery/routes/experiment-code/README.md), [`../discovery/policies/managed-experiment-code-posture.md`](../discovery/policies/managed-experiment-code-posture.md) | Decide which concrete user step merits promotion first: record, materialize, observe editable folder, prepare rerun, or GUI review. |
| Running Measurement Monitor | Discovery / validation question | No promoted implementation owner yet. Future app/runtime capability question for observing multiple Python-driven measurements without controlling hardware or scheduling. | [`../engineering/workflow-validation-map.md`](../engineering/workflow-validation-map.md), [`../evidence/evidence-register.md`](../evidence/evidence-register.md) | Validate whether Python measurement scripts can emit lifecycle/progress/partial-data events that a long-lived local GUI can monitor across multiple active measurements. |
| Calibration Continuation Review | Discovery / implementation-candidate evidence | No promoted implementation owner yet. Current evidence is discovery/candidate-shaped and should not be treated as a maintained calibration engine. | [`../discovery/routes/calibration-continuation/decision.md`](../discovery/routes/calibration-continuation/decision.md), [`../discovery/routes/calibration-continuation/README.md`](../discovery/routes/calibration-continuation/README.md) | Promote only around explicit user actions, review state transitions, and route-native acceptance criteria. |

## Update Rule

Update this map when a branch changes product capability maturity, product
boundary, evidence owner, or advancement questions.

Do not use this file to list every implementation entrypoint or test. Use
[`../engineering/implementation-register.md`](../engineering/implementation-register.md)
for live implementation ownership.
