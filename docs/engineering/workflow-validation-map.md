# Workflow Validation Map

## Status

Workflow validation owner.

## Purpose

This map organizes Scopecat progress by user workflow rather than by candidate
file, fixture family, or code module. Use it to decide what the next prototype
or vertical slice should validate.

[`../product/capability-map.md`](../product/capability-map.md) records product
capabilities, maturity, evidence, and open advancement questions.
[`implementation-register.md`](implementation-register.md) records live
implementation owners. This document records the user workflow thread and its
validated or missing steps.

## Current Workflow Focus

The main composition gap is the legacy portable handoff workflow: import or
record a legacy-backed measurement into Scopecat storage, select one stored
measurement, export a handoff package, preview it on another computer, and
import it into that computer's storage.

The validated ends already exist: Measurement Records can store legacy-backed
records and Handoff can preview/gate/import one ready package measurement into
another storage root. The missing seam is selected stored Measurement Record to
single-measurement handoff package export, including identity continuity and
portable/export artifact-boundary behavior for that package.

## Current Validation Tasks

| ID | Task | Workflow | Capabilities | Evidence / Owner Links |
| --- | --- | --- | --- | --- |
| `VT-001` | Validate selected stored Measurement Record to single-measurement handoff package export. | Legacy measurement portable handoff. | Measurement Records, Handoff Packages. | [`../product/capability-map.md`](../product/capability-map.md), [`implementation-register.md`](implementation-register.md), [`prototype-boundaries/measurement-records-creation-lifecycle.md`](prototype-boundaries/measurement-records-creation-lifecycle.md), [`prototype-boundaries/handoff.md`](prototype-boundaries/handoff.md) |

Keep this section short. Add a task only when it is the current or next
validation target; use the workflow table below for broader background.

## How To Read

- Start with rows marked `Composition gap`; those are the clearest next
  workflow-seam candidates.
- Rows marked `Engineering prototype` have live route-local implementation
  owners, but they are not production vertical slices or maintained product
  capabilities.
- Rows marked `Discovery evidence` with `Unpromoted route owner` should not be
  copied into live code unless they close a named workflow step, seam, or risk
  question.
- Use `Next Validation Question` to choose the next prototype.
- Use [`../product/capability-map.md`](../product/capability-map.md) to find
  product capabilities, maturity, supporting evidence, and open advancement
  questions.
- Use [`implementation-register.md`](implementation-register.md) to find live
  implementation owners and their detailed module/boundary docs.

## Status Vocabulary

| Workflow State | Meaning |
| --- | --- |
| Discovery evidence | Evidence exists, but no accepted live implementation owns the workflow step. |
| Engineering prototype | A route-local production-shaped prototype validates a named workflow step, seam, or risk question. |
| Production vertical slice | A scoped user workflow is accepted from entrypoint to durable state or output with defined failure behavior. |
| Superseded | Historical workflow evidence remains useful but is no longer the active path. |

Use `Gap Type` separately for topology such as `None`, `Composition gap`, or
`Unpromoted route owner`.

## Workflow Threads

| Workflow Thread | User Job | Type | Workflow State | Gap Type | Validated Steps | Missing Steps Or Seams | Next Validation Question |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Legacy external run becomes visible in local storage | Record declared facts about an externally executed legacy run so it can be reviewed in Scopecat without rewriting the legacy system first. | Single workflow | Engineering prototype | None | Create a `legacy_system` Measurement Records shell; write `legacy-run-receipt.json`; optionally attach reviewed converted normalized primary data to the same record; optionally record parameter, setup, code, artifact, and evidence references; list/review visible storage. | Legacy file observation, legacy parsing, adapter discovery, legacy code execution, reference repair, GUI state persistence, and scientific validity remain unvalidated. | Maintenance only unless a new brownfield workflow seam is named. |
| Normalized primary data becomes a durable Measurement Record | Import reviewed normalized primary CSV into durable local Measurement Records storage. | Single workflow | Engineering prototype | None | Create record shell; write primary data; validate normalized table shape; finalize; project read model; catalog/refresh read model; durable import rolls back synchronous partial new-record failures. | Final storage schema, existing-record merge import, manifest replacement, conflict resolution beyond accepted no-overwrite paths, and shared domain model remain unvalidated. | Decide separately if existing-record import/update becomes a production vertical slice. |
| Source-root data becomes a local handoff package for review | Package one or more declared normalized primary data files from a caller-provided source root for local review. | Single workflow | Engineering prototype | None | Validate write request; copy declared primary CSV files after digest/size preflight; write directory-shaped package subset; reopen package; optionally write local inspection HTML. | Archive format, signatures/authenticity, package import, final package format, linked-context payload packaging, and GUI architecture remain unvalidated. | Maintenance only unless the package export source changes to stored Measurement Records. |
| Handoff package is received and imported into local storage | Review a handoff package on a receiving side and import one selected measurement into local storage. | Seam workflow | Engineering prototype | None | Open package read-only; observe manifest-declared integrity; run receiving gate; create non-mutating import plan; adapt one ready measurement into Measurement Records durable import; summarize import receipt and retry reasonableness. | Batch import, archive extraction/trust, signatures/authenticity, linked-context payload import, conflict resolution beyond delegated durable import rules, and persistent receiving review state remain unvalidated. | Decide separately if batch receiving or trust/authenticity is the next user risk. |
| Legacy measurement portable handoff | Move one selected legacy-backed measurement from one Scopecat storage root to another computer where it can be previewed and imported. | Composition workflow | Engineering prototype | Composition gap | Existing validated ends: legacy external run can become local Measurement Records storage; handoff package can be opened, previewed, gated, and imported into another Measurement Records storage root. | The missing seam is selected stored Measurement Record to handoff package export, including identity continuity from legacy run to package measurement to receiving-side record. Portable/export artifact boundary and package redaction behavior need explicit validation. | Validate `selected stored measurement -> single-measurement handoff package export` as a narrow composition prototype. |
| Approved `uv sync` intent becomes local environment-operation review evidence | Run an approved environment manager operation and capture bounded review evidence before run preparation or operator review consumes it. | Single workflow | Engineering prototype | None | Parse validated `uv sync` intent; execute bounded `uv sync`; capture typed result; review operation; optionally run bounded interpreter fact probe after successful review-clean sync. | Runtime readiness, package-state truth, selected-code execution, notebook execution, hardware/service probing, multi-manager abstraction, cancellation UI, and portable projection of local paths remain unvalidated. | Pick one separate route extension: manifest integration, runtime-readiness review, manager expansion, execution hardening, or handoff continuity. |
| Parameter state is reviewed, stored, read, and consumed for manual pre-run review | Let an operator review adapter or calibration parameter-state facts before a run without applying hardware changes. | Single workflow | Engineering prototype | None | Adapter-authored import preview; explicit review/commit; no-overwrite storage writer; manifest/receipt read view; source-agnostic projection; selection context; parameter-state-local run-preparation consumption, gate, scope alignment, and review chain. | Hardware apply, current instrument-state claims, external compatibility-file writing, live write-back, catalog discovery, setup-binding mutation, automatic run start, and shared run-context schema remain unvalidated. | Decide separately whether prepared-run becomes its own live route owner. |
| Calibration continuation review | Recover or continue calibration work using reviewable fit, evidence, and action summaries. | Single or composition workflow | Discovery evidence | Unpromoted route owner | Multiple candidate summaries validate review surface, action recording, fit recovery, continuation composition, and parameter-state handoff pressure. | No live route-native workflow entrypoint owns explicit user actions, review state transitions, or production-shaped acceptance criteria. | Promote only if a narrow calibration continuation workflow has user-step acceptance criteria. |
| Prepared run context and approval | Prepare a run from selected context and review it before execution. | Single workflow | Discovery evidence | Unpromoted route owner | Candidate evidence exists for context construction, review gate, acknowledgement-aware review, view-state projection, and optional environment-operation evidence projection. | No live prepared-run route owner. Automatic run start, execution permission, hardware safety, and shared run-context schema remain unvalidated. | Promote only around a workflow-shaped prepared-run boundary with command/result model and acceptance criteria. |

## Update Rule

Update this map when a branch:

- adds, promotes, supersedes, or retires a workflow step;
- validates a seam between two accepted routes;
- changes a workflow's generated artifact, portable/export, or redaction
  boundary;
- discovers that a validation artifact is being counted as progress without
  closing a named workflow or capability question.

Keep detailed API and code ownership in module READMEs and prototype-boundary
notes.
Keep this map focused on the user workflow thread.
