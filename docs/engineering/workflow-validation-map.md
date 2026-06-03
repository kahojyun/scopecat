# Use Case And Workflow Validation Map

## Status

Use-case and workflow validation owner.

## Purpose

This map organizes Scopecat progress by common product-delivery scopes rather
than by candidate file, fixture family, or code module. Use it to decide what
the next prototype or vertical slice should validate.

[`../product/capability-map.md`](../product/capability-map.md) records product
capabilities, maturity, evidence, and open advancement questions.
[`implementation-register.md`](implementation-register.md) records live
implementation owners. This document records user journeys, workflows, use
cases, scenarios, operations, and their validated or missing behavior.

## Current Focus

The main composition gap is the legacy portable handoff user journey: import or
record a legacy-backed measurement into Scopecat storage, select one stored
measurement, export a handoff package, preview it on another computer, and
import it into that computer's storage.

The validated ends already exist: Measurement Records can store legacy-backed
records and Handoff can preview/gate/import one ready package measurement into
another storage root. The missing seam is selected stored Measurement Record to
single-measurement handoff package export, including identity continuity and
portable/export artifact-boundary behavior for that package.

## Reading Rules

Start with the `End-To-End User Journeys` section for product direction. Use
`Use Cases And Workflow Segments` for promotable vertical-slice pressure. Use
`Scenarios And Operations` only for route-local validation, review, or
technical-risk work. Then use
[`implementation-register.md`](implementation-register.md) to find the live
module owners and boundary detail.

Do not treat this map as an issue tracker. Active execution work belongs in
issues, PRs, or branch-specific plans when implementation starts. This map
records product-scope state and validation questions.

## Scope Vocabulary

Use common scope terms:

| Level | Meaning |
| --- | --- |
| User journey | Broad end-to-end path across one or more capabilities. |
| Workflow | User-visible sequence of activities that completes a goal. |
| Use case | Scoped user goal or workflow segment validated independently. |
| Scenario | Concrete review or acceptance situation used for validation. |
| Operation | Single approved action, command, mutation, or read/projection run. |

Use common maturity terms from
[`delivery-maturity-model.md`](delivery-maturity-model.md): `Discovery`,
`Engineering prototype`, `Production vertical slice`, `Production readiness`,
or `Maintained product capability`.

## End-To-End User Journeys

| User Journey | User Goal | Maturity | Supported Use Cases | Missing Use Cases Or Seams | Next Validation Question |
| --- | --- | --- | --- | --- | --- |
| Legacy measurement portable handoff | Move one selected legacy-backed measurement from one Scopecat storage root to another computer where it can be previewed and imported. | Engineering prototype | Legacy external run can become local Measurement Records storage; handoff package can be opened, previewed, gated, and imported into another Measurement Records storage root. | Selected stored Measurement Record to single-measurement handoff package export, including identity continuity from legacy run to package measurement to receiving-side record. Portable/export artifact boundary and package redaction behavior need explicit validation. | Validate `selected stored measurement -> single-measurement handoff package export` as a narrow use case. |

## Use Cases And Workflow Segments

| Use Case | User Goal | Maturity | Capability Areas | Supported Behavior | Missing Behavior | Next Validation Question |
| --- | --- | --- | --- | --- | --- | --- |
| Legacy external run becomes visible in local storage | Record declared facts about an externally executed legacy run so it can be reviewed in Scopecat without rewriting the legacy system first. | Engineering prototype | Measurement Records | Create a `legacy_system` Measurement Records shell; write `legacy-run-receipt.json`; optionally attach reviewed converted normalized primary data to the same record; optionally record parameter, setup, code, artifact, and evidence references; list/review visible storage. | Legacy file observation, legacy parsing, adapter discovery, legacy code execution, reference repair, GUI state persistence, and scientific validity remain unvalidated. | Maintenance only unless a new brownfield use case is named. |
| Normalized primary data becomes a durable Measurement Record | Import reviewed normalized primary CSV into durable local Measurement Records storage. | Engineering prototype | Measurement Records | Create record shell; write primary data; validate normalized table shape; finalize; project read model; catalog/refresh read model; durable import rolls back synchronous partial new-record failures. | Final storage schema, existing-record merge import, manifest replacement, conflict resolution beyond accepted no-overwrite paths, and shared domain model remain unvalidated. | Decide separately if existing-record import/update becomes a production vertical slice. |
| Source-root data becomes a local handoff package for review | Package one or more declared normalized primary data files from a caller-provided source root for local review. | Engineering prototype | Handoff Packages | Validate write request; copy declared primary CSV files after digest/size preflight; write directory-shaped package subset; reopen package; optionally write local inspection HTML. | Archive format, signatures/authenticity, package import, final package format, linked-context payload packaging, and GUI architecture remain unvalidated. | Maintenance only unless the package export source changes to stored Measurement Records. |
| Handoff package is received and imported into local storage | Review a handoff package on a receiving side and import one selected measurement into local storage. | Engineering prototype | Handoff Packages, Measurement Records | Open package read-only; observe manifest-declared integrity; run receiving gate; create non-mutating import plan; adapt one ready measurement into Measurement Records durable import; summarize import receipt and retry reasonableness. | Batch import, archive extraction/trust, signatures/authenticity, linked-context payload import, conflict resolution beyond delegated durable import rules, and persistent receiving review state remain unvalidated. | Decide separately if batch receiving or trust/authenticity is the next user risk. |
| Parameter state review before manual run preparation | Let an operator review adapter or calibration parameter-state facts before a run without applying hardware changes. | Engineering prototype | Parameter State Review | Adapter-authored import preview; explicit review/commit; no-overwrite storage writer; manifest/receipt read view; source-agnostic projection; selection context; parameter-state-local run-preparation consumption, gate, scope alignment, and review chain. | Hardware apply, current instrument-state claims, external compatibility-file writing, live write-back, catalog discovery, setup-binding mutation, automatic run start, and shared run-context schema remain unvalidated. | Decide separately whether prepared-run becomes its own live route owner. |

## Scenarios And Operations

| Item | Level | Goal | Maturity | Supported Behavior | Missing Behavior | Next Validation Question |
| --- | --- | --- | --- | --- | --- | --- |
| Approved `uv sync` intent becomes local environment-operation review evidence | Operation | Run an approved environment manager operation and capture bounded review evidence before run preparation or operator review consumes it. | Engineering prototype | Parse validated `uv sync` intent; execute bounded `uv sync`; capture typed result; review operation; optionally run bounded interpreter fact probe after successful review-clean sync. | Runtime readiness, package-state truth, selected-code execution, notebook execution, hardware/service probing, multi-manager abstraction, cancellation UI, and portable projection of local paths remain unvalidated. | Pick one separate route extension: manifest integration, runtime-readiness review, manager expansion, execution hardening, or handoff continuity. |
| Calibration continuation review | Scenario | Recover or continue calibration work using reviewable fit, evidence, and action summaries. | Discovery | Multiple candidate summaries validate review surface, action recording, fit recovery, continuation composition, and parameter-state handoff pressure. | No live route-native workflow entrypoint owns explicit user actions, review state transitions, or production-shaped acceptance criteria. | Promote only if a narrow calibration continuation use case has user-step acceptance criteria. |
| Prepared run context and approval | Scenario | Prepare a run from selected context and review it before execution. | Discovery | Candidate evidence exists for context construction, review gate, acknowledgement-aware review, view-state projection, and optional environment-operation evidence projection. | No live prepared-run route owner. Automatic run start, execution permission, hardware safety, and shared run-context schema remain unvalidated. | Promote only around a prepared-run use case with command/result model and acceptance criteria. |

## Update Rule

Update this map when a branch:

- adds, promotes, supersedes, or retires a user journey, workflow, use case,
  scenario, operation, or step;
- validates a seam between two accepted routes;
- changes generated artifact, portable/export, or redaction behavior for one of
  the scoped rows above;
- discovers that a validation artifact is being counted as progress without
  closing a named workflow or capability question.

Keep detailed API and code ownership in module READMEs and prototype-boundary
notes.
Keep this map focused on user journeys, use cases, scenarios, and operations.
