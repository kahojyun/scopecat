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
  for live modules, entrypoints, tests, fixtures, and prototype-boundary notes.

## Capability Map

| Capability | Maturity | User Value | Supported Workflows | Product Boundary | Evidence | Open Advancement Questions |
| --- | --- | --- | --- | --- | --- | --- |
| Measurement Records | Engineering prototype | Make measurements visible, reviewable, durable, and usable as anchors for later handoff and context. | Normalized primary data becomes a durable Measurement Record; legacy external run becomes visible in local storage; stored records support later review and handoff workflows. | Scopecat stores declared measurement facts and reviewed normalized data under a caller-provided storage root. Legacy run storage records declared external-run facts and optional converted primary data without requiring immediate legacy-system replacement. | Measurement Records unit tests, legacy storage scenario fixtures, measurement fixture families, and prototype boundary notes. | Decide whether selected stored measurement export, existing-record update/import, running measurement lifecycle, or storage schema readiness is the next vertical-slice pressure. |
| Handoff Packages | Engineering prototype | Move selected measurement data across computers with open-before-import review. | Source-root data becomes a local handoff package; handoff package is opened, previewed, gated, planned, and imported into another storage root. | Scopecat-authored directory packages can be written, reopened, inspected locally, integrity-observed, receiving-gated, import-planned, and imported through Measurement Records durable import. | Handoff fixture families, prototype fixtures, module tests, handoff package boundary notes, and durable import boundary note. | Validate selected stored Measurement Record to single-measurement handoff package export; decide later trust/authenticity, batch receiving, archive format, and linked-context payload import questions. |
| Parameter State Review | Engineering prototype | Let users review, store, select, and consume parameter-state facts before a run without automatic hardware mutation. | Parameter state is reviewed, stored, read, selected, and consumed for manual pre-run review. | Scopecat owns adapter-authored previews, reviewed parameter-state storage, manifest/receipt read views, source-agnostic projections, selection context, and route-local pre-run review-chain consumption. | Parameter-state unit tests, parameter fixture families, and parameter-state boundary note. | Decide whether compatibility-file writing, hardware apply, catalog discovery, automatic run start, or a shared parameter/run-context schema is justified by a workflow. |
| Environment Operation | Engineering prototype | Capture bounded environment-manager operation evidence for review before other workflows consume it. | Approved environment-manager intent becomes local operation evidence for review before run preparation or operator review consumes it. | Scopecat can execute approved `uv sync` intent through a bounded route-local path, produce typed result/review objects, and optionally run a bounded interpreter fact probe. | Environment-operation unit tests, environment fixture families, prototype fixtures, and environment-operation boundary note. | Decide whether runtime readiness, manifest integration, manager expansion, execution hardening, or GUI/runtime monitoring is the next validated product need. |
| Experiment Code Context | Discovery / validation evidence | Preserve and later select, compare, materialize, or restore experiment code context without forcing users into Git-facing workflow first. | Explicit experiment-code recording and later managed-code/materialization workflows. | No live product capability owner yet. Discovery evidence supports explicit code context records, include policy, managed version pressure, and materialization pressure. | Experiment-code discovery route, managed experiment-code policy, validation results, and implementation candidates. | Decide which concrete user step merits promotion first: record, materialize, observe editable folder, prepare rerun, or GUI review. |
| Running Measurement Monitor | Discovery / validation question | Keep a local GUI open while multiple Python-driven measurements show lifecycle, progress, partial preview, stale/failure state, and completion into durable records. | Running Python measurements emit lightweight Scopecat events for live local review. | No accepted live owner yet. This is a future app-runtime capability question, not a commitment to a remote backend, scheduler, workflow engine, or hardware-control layer. | User workflow pressure and adjacent Measurement Records storage/review evidence; no production-shaped live-monitor prototype yet. | Validate whether Python measurement scripts can emit lifecycle/progress/partial-data events that a long-lived local GUI can monitor across multiple active measurements without controlling the experiment. |
| Calibration Continuation Review | Discovery / implementation-candidate evidence | Help users recover or continue calibration work through reviewable fit, evidence, and action summaries. | Calibration continuation review and action recording. | No live product capability owner yet. Current evidence is discovery/candidate-shaped and should not be treated as a maintained calibration engine. | Calibration continuation discovery decision, route README, and validation results. | Promote only around explicit user actions, review state transitions, and route-native acceptance criteria. |

## Update Rule

Update this map when a branch changes product capability maturity, supported
workflows, user value, evidence, or advancement questions.

Do not use this file to list every implementation entrypoint or test. Use
[`../engineering/implementation-register.md`](../engineering/implementation-register.md)
for live implementation ownership.
