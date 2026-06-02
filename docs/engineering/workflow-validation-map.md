# Workflow Validation Map

## Status

Workflow validation owner.

## Purpose

This map organizes Scopecat progress by user workflow rather than by candidate
file, fixture family, or code module. Use it to decide what the next prototype
or vertical slice should validate.

[`vertical-slice-register.md`](vertical-slice-register.md) records the
implementation owners for accepted slices. This document records the user
workflow thread and its validated or missing steps.

## Status Vocabulary

| Status | Meaning |
| --- | --- |
| Discovery evidence | Evidence exists, but no accepted live implementation owns the workflow step. |
| Implementation candidate | Candidate behavior exists and may have fixtures/tests, but it is not an accepted live route owner. |
| Engineering prototype | A route-local production-shaped prototype validates a named workflow step, seam, or risk question. |
| Production vertical slice | A scoped user workflow is accepted from entrypoint to durable state or output with defined failure behavior. |
| Composition gap | Adjacent validated steps exist, but the user workflow still lacks a validated seam between them. |
| Superseded | Historical workflow evidence remains useful but is no longer the active path. |

## Workflow Threads

| Workflow Thread | User Job | Type | Status | Validated Steps | Missing Steps Or Seams | Live Owner | Next Validation Question |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Legacy external run becomes visible in local storage | Record declared facts about an externally executed legacy run so it can be reviewed in Scopecat without rewriting the legacy system first. | Single workflow | Engineering prototype | Create a `legacy_system` Measurement Records shell; write `legacy-run-receipt.json`; optionally attach reviewed converted normalized primary data to the same record; optionally record parameter, setup, code, artifact, and evidence references; list/review visible storage. | Legacy file observation, legacy parsing, adapter discovery, legacy code execution, reference repair, GUI state persistence, and scientific validity remain unvalidated. | [`src/scopecat/measurement_records/README.md`](../../src/scopecat/measurement_records/README.md) | Maintenance only unless a new brownfield workflow seam is named. |
| Normalized primary data becomes a durable Measurement Record | Import reviewed normalized primary CSV into durable local Measurement Records storage. | Single workflow | Engineering prototype | Create record shell; write primary data; validate normalized table shape; finalize; project read model; catalog/refresh read model; durable import rolls back synchronous partial new-record failures. | Final storage schema, existing-record merge import, manifest replacement, conflict resolution beyond accepted no-overwrite paths, and shared domain model remain unvalidated. | [`src/scopecat/measurement_records/README.md`](../../src/scopecat/measurement_records/README.md) | Decide separately if existing-record import/update becomes a production vertical slice. |
| Source-root data becomes a local handoff package for review | Package one or more declared normalized primary data files from a caller-provided source root for local review. | Single workflow | Engineering prototype | Validate write request; copy declared primary CSV files after digest/size preflight; write directory-shaped package subset; reopen package; optionally write local inspection HTML. | Archive format, signatures/authenticity, package import, final package format, linked-context payload packaging, and GUI architecture remain unvalidated. | [`src/scopecat/handoff/README.md`](../../src/scopecat/handoff/README.md) | Maintenance only unless the package export source changes to stored Measurement Records. |
| Handoff package is received and imported into local storage | Review a handoff package on a receiving side and import one selected measurement into local storage. | Seam workflow | Engineering prototype | Open package read-only; observe manifest-declared integrity; run receiving gate; create non-mutating import plan; adapt one ready measurement into Measurement Records durable import; summarize import receipt and retry reasonableness. | Batch import, archive extraction/trust, signatures/authenticity, linked-context payload import, conflict resolution beyond delegated durable import rules, and persistent receiving review state remain unvalidated. | [`src/scopecat/handoff/README.md`](../../src/scopecat/handoff/README.md), [`src/scopecat/measurement_records/README.md`](../../src/scopecat/measurement_records/README.md) | Decide separately if batch receiving or trust/authenticity is the next user risk. |
| Legacy measurement portable handoff | Move one selected legacy-backed measurement from one Scopecat storage root to another computer where it can be previewed and imported. | Composition workflow | Composition gap | Existing validated ends: legacy external run can become local Measurement Records storage; handoff package can be opened, previewed, gated, and imported into another Measurement Records storage root. | The missing seam is selected stored Measurement Record to handoff package export, including identity continuity from legacy run to package measurement to receiving-side record. Portable/export boundary and package redaction posture need explicit validation. | None for the full workflow. The ends are owned by Measurement Records and Handoff. | Validate `selected stored measurement -> single-measurement handoff package export` as a narrow composition prototype. |
| Approved `uv sync` intent becomes local environment-operation review evidence | Run an approved environment manager operation and capture bounded review evidence before run preparation or operator review consumes it. | Single workflow | Engineering prototype | Parse validated `uv sync` intent; execute bounded `uv sync`; capture typed result; review operation; optionally run bounded interpreter fact probe after successful review-clean sync. | Runtime readiness, package-state truth, selected-code execution, notebook execution, hardware/service probing, multi-manager abstraction, cancellation UI, and portable projection of local paths remain unvalidated. | [`src/scopecat/environment_operation/README.md`](../../src/scopecat/environment_operation/README.md) | Pick one separate route extension: manifest integration, runtime-readiness review, manager expansion, execution hardening, or handoff continuity. |
| Parameter state is reviewed, stored, read, and consumed for manual pre-run review | Let an operator review adapter or calibration parameter-state facts before a run without applying hardware changes. | Single workflow | Engineering prototype | Adapter-authored import preview; explicit review/commit; no-overwrite storage writer; manifest/receipt read view; source-agnostic projection; selection context; parameter-state-local run-preparation consumption, gate, scope alignment, and review chain. | Hardware apply, current instrument-state claims, external compatibility-file writing, live write-back, catalog discovery, setup-binding mutation, automatic run start, and shared run-context schema remain unvalidated. | [`src/scopecat/parameter_state/README.md`](../../src/scopecat/parameter_state/README.md) | Decide separately whether prepared-run becomes its own live route owner. |
| Calibration continuation review | Recover or continue calibration work using reviewable fit, evidence, and action summaries. | Single or composition workflow | Implementation candidate | Multiple candidate summaries validate review surface, action recording, fit recovery, continuation composition, and parameter-state handoff pressure. | No live route-native workflow entrypoint owns explicit user actions, review state transitions, or production-shaped acceptance criteria. | None. | Promote only if a narrow calibration continuation workflow has user-step acceptance criteria. |
| Prepared run context and approval | Prepare a run from selected context and review it before execution. | Single workflow | Implementation candidate | Candidate evidence exists for context construction, review gate, acknowledgement-aware review, view-state projection, and optional environment-operation evidence projection. | No live prepared-run route owner. Automatic run start, execution permission, hardware safety, and shared run-context schema remain unvalidated. | None. | Promote only around a workflow-shaped prepared-run boundary with command/result model and acceptance criteria. |

## Update Rule

Update this map when a branch:

- adds, promotes, supersedes, or retires a workflow step;
- validates a seam between two accepted routes;
- changes a workflow's generated artifact, portable/export, or redaction
  boundary;
- discovers that an implementation candidate is being copied without closing a
  named workflow question.

Keep detailed API and code ownership in module READMEs and prototype-boundary
notes.
Keep this map focused on the user workflow thread.
