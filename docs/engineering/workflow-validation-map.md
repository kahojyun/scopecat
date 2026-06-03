# Use Case And Workflow Validation Map

## Status

Use-case and workflow validation owner.

## Purpose

This map organizes Scopecat validation progress by use case, workflow segment,
scenario evidence, and operation evidence rather than by candidate file,
fixture family, or code module. Use it to decide what the next use-case-driven
prototype should validate.

Use stable `UC-*` IDs for use cases and workflow segments that can drive
use-case-driven validation. Do not assign stable IDs to scenarios or
operations unless they are promoted into named use cases.
Use `UC-CAND-*` IDs for missing or candidate use cases that are visible enough
to sequence, but not yet validated enough to join the `UC-*` table.

## Current Focus

The main composition gap is the Portable Measurement Handoff use case:
record or import an externally produced measurement into Scopecat storage,
select one stored measurement, export a handoff package, preview it on another
computer, and import it into that computer's storage.

The validated ends already exist: Measurement Records can store legacy-backed
records and Handoff can preview/gate/import one ready package measurement into
another storage root. The missing seam is selected stored Measurement Record to
single-measurement handoff package export, including identity continuity and
portable/export artifact-boundary behavior for that package.

## Reading Rules

Use `Use Cases And Workflow Segments` for promotable validation focus.
Use `Scenarios And Operations` only for route-local validation, review, or
technical-risk evidence.

Do not treat this map as an issue tracker. Active execution work belongs in
issues, PRs, or branch-specific plans when implementation starts. This map
records product-scope state and validation questions.

Promote `UC-CAND-*` to `UC-*` only when the use case has acceptance criteria,
owned validation evidence, and a clear maturity state. Retire candidate IDs
instead of reusing them if the candidate is merged, split, or rejected.

## Scope Vocabulary

Use common scope terms:

| Level | Meaning |
| --- | --- |
| Workflow | User-visible sequence of activities that completes a goal. |
| Use case | Scoped user goal or workflow segment validated independently. |
| Scenario | Concrete review or acceptance situation used for validation. |
| Operation | Single approved action, command, mutation, or read/projection run. |

Use common maturity terms from
[`delivery-maturity-model.md`](delivery-maturity-model.md): `Discovery`,
`Engineering prototype`, `Production vertical slice`, `Production readiness`,
or `Maintained product capability`.

## Candidate Use Cases

Candidate use cases are the named queue for thin implementation slices that are
visible in traceability or roadmap planning but not yet mature enough to become
`UC-*`.

| ID | Candidate Use Case | Supports Journey | Capability Areas | Candidate Source | Promotion Question |
| --- | --- | --- | --- | --- | --- |
| UC-CAND-001 | Export one selected stored Measurement Record to a preview-ready single-measurement handoff package | JNY-001 | CAP-001, CAP-002 | Main composition gap in the current focus. | Can package export from stored records preserve identity, primary-data references, missing context, and portable/export boundaries across the validated handoff ends? |
| UC-CAND-002 | Prepared-run context review and acknowledgement | JNY-002 | CAP-003, CAP-005, CAP-004, CAP-001 | Prepared-run scenario evidence. | Does the user-facing use case have explicit input, review, acknowledgement or deferral, and no-run-start semantics? |
| UC-CAND-003 | First promoted experiment-code context step | JNY-005 | CAP-005, CAP-004 | Experiment-code discovery and implementation-candidate evidence. | Which one step has an independently useful user goal: record, compare, materialize, observe editable folder, prepare rerun, or GUI review? |
| UC-CAND-004 | Lifecycle, progress, and partial-data event recording for running measurement inspection | JNY-004 | CAP-006, CAP-001 | Running measurement monitoring discovery evidence. | Can Python-driven measurements emit reviewable lifecycle, progress, and partial-data events without granting scan control? |
| UC-CAND-005 | Calibration continuation use case with stable review state and action recording | JNY-003 | CAND-001, CAP-003, CAP-001 | Calibration continuation scenario evidence. | Do repeated calibration continuation cases require stable review state, continuation actions, and support expectations beyond one scenario? |
| UC-CAND-006 | Declared context comparison against a selected reference | JNY-006 | CAP-001, CAP-005, CAP-003 | Selected-reference comparison discovery evidence. | Can Scopecat compare declared context facts and selected code context without claiming setup truth or domain judgment? |

## Use Cases And Workflow Segments

| ID | Use Case Or Workflow Segment | Supports Journey | Maturity | Capability Areas | Supported Behavior | Missing Behavior | Next Validation Question |
| --- | --- | --- | --- | --- | --- | --- | --- |
| UC-001 | Legacy external run becomes visible in local storage | JNY-001 | Engineering prototype | CAP-001 | Create a `legacy_system` Measurement Records shell; write `legacy-run-receipt.json`; optionally attach reviewed converted normalized primary data to the same record; optionally record parameter, setup, code, artifact, and evidence references; list/review visible storage. | Legacy file observation, legacy parsing, adapter discovery, legacy code execution, reference repair, GUI state persistence, and scientific validity remain unvalidated. | Maintenance only unless a new brownfield use case is named. |
| UC-002 | Normalized primary data becomes a durable Measurement Record | JNY-001 | Engineering prototype | CAP-001 | Import reviewed normalized primary CSV into durable local Measurement Records storage; create record shell; write primary data; validate normalized table shape; finalize; project read model; catalog/refresh read model; durable import rolls back synchronous partial new-record failures. | Final storage schema, existing-record merge import, manifest replacement, conflict resolution beyond accepted no-overwrite paths, and shared domain model remain unvalidated. | Decide separately if existing-record import/update becomes a production vertical slice. |
| UC-003 | Source-root data becomes a local handoff package for review | JNY-001 | Engineering prototype | CAP-002 | Package one or more declared normalized primary data files from a caller-provided source root for local review; validate write request; copy declared primary CSV files after digest/size preflight; write directory-shaped package subset; reopen package; optionally write local inspection HTML. | Archive format, signatures/authenticity, package import, final package format, linked-context payload packaging, and GUI architecture remain unvalidated. | Maintenance only unless the package export source changes to stored Measurement Records. |
| UC-004 | Handoff package is received and imported into local storage | JNY-001 | Engineering prototype | CAP-002, CAP-001 | Review a handoff package on a receiving side and import one selected measurement into local storage; open package read-only; observe manifest-declared integrity; run receiving gate; create non-mutating import plan; adapt one ready measurement into Measurement Records durable import; summarize import receipt and retry reasonableness. | Batch import, archive extraction/trust, signatures/authenticity, linked-context payload import, conflict resolution beyond delegated durable import rules, and persistent receiving review state remain unvalidated. | Decide separately if batch receiving or trust/authenticity is the next user risk. |
| UC-005 | Parameter state review before manual run preparation | JNY-002 | Engineering prototype | CAP-003 | Let an operator review adapter or calibration parameter-state facts before a run without applying hardware changes; adapter-authored import preview; explicit review/commit; no-overwrite storage writer; manifest/receipt read view; source-agnostic projection; selection context; parameter-state-local run-preparation consumption, gate, scope alignment, and review chain. | Hardware apply, current instrument-state claims, external compatibility-file writing, live write-back, catalog discovery, setup-binding mutation, automatic run start, and shared run-context schema remain unvalidated. | Decide separately whether prepared-run becomes its own live route owner. |

## Scenarios And Operations

| Item | Level | Supports Journey Or Use Case | Evidence State | Supported Behavior | Missing Behavior | Next Validation Question |
| --- | --- | --- | --- | --- | --- | --- |
| Approved `uv sync` intent becomes local environment-operation review evidence | Operation | JNY-002; JNY-005 | Engineering prototype evidence | Parse validated `uv sync` intent; execute bounded `uv sync`; capture typed result; review operation; optionally run bounded interpreter fact probe after successful review-clean sync. | Runtime readiness, package-state truth, selected-code execution, notebook execution, hardware/service probing, multi-manager abstraction, cancellation UI, and portable projection of local paths remain unvalidated. | Pick one separate route extension: manifest integration, runtime-readiness review, manager expansion, execution hardening, or handoff continuity. |
| Calibration continuation review | Scenario | JNY-003 | Discovery evidence | Multiple candidate summaries validate review surface, action recording, fit recovery, continuation composition, and parameter-state handoff pressure. | No live route-native workflow entrypoint owns explicit user actions, review state transitions, or production-shaped acceptance criteria. | Promote only if a narrow calibration continuation use case has user-step acceptance criteria. |
| Prepared run context and acknowledgement | Scenario | JNY-002 | Discovery evidence | Candidate evidence exists for context construction, review gate, acknowledgement-aware review, view-state projection, and optional environment-operation evidence projection. | No live prepared-run route owner. Automatic run start, execution permission, hardware safety, and shared run-context schema remain unvalidated. | Promote only around a prepared-run use case with command/result model and acceptance criteria. |

## Update Rule

Update this map when a branch:

- adds, promotes, supersedes, or retires a workflow segment, use case,
  candidate use case, scenario, operation, or step;
- validates a seam between two accepted routes;
- changes generated artifact, portable/export, or redaction behavior for one of
  the scoped rows above;
- discovers that a validation artifact is being counted as progress without
  closing a named use case, workflow, or capability question.

Keep detailed API and code ownership in module READMEs and prototype-boundary
notes.
Keep this map focused on use cases, workflow segments, scenarios, and
operations. Update the target journey map when a target user journey changes
and the brownfield transition architecture when migration state or ownership
posture changes.
