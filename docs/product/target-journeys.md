# Journey And Use Case Index

## Status

Canonical target journey and use case index.

## Purpose

Own Scopecat's durable `JNY-*`, `UC-*`, and `UC-CAND-*` IDs and the current
relationship between journeys, use cases, candidate use cases, supporting
workflows, and product capabilities.

Use this file as the first stop when deciding what user journey or use case a
discovery result, prototype, validation row, ADR, risk, or implementation owner
supports. Keep validation evidence in
[`../engineering/workflow-validation-map.md`](../engineering/workflow-validation-map.md),
capability maturity in [`target-capabilities.md`](target-capabilities.md),
brownfield transition posture in
[`../brownfield/transition-architecture.md`](../brownfield/transition-architecture.md),
and implementation ownership in
[`../engineering/implementation-register.md`](../engineering/implementation-register.md).

## Reading Rules

- A target journey is a user-recognizable end-to-end job, not a context family,
  code module, storage route, or implementation capability.
- A use case is a scoped user goal or workflow segment that can be validated
  independently.
- `UC-CAND-*` rows are visible enough to sequence, but not mature enough to be
  accepted use cases.
- Supporting workflows may feed several journeys without becoming standalone
  target journeys.
- Do not infer implementation ownership from this index. Live owners remain in
  the implementation register and module README files.
- Do not reuse retired IDs.

## Lifecycle Composition

Real experiment work usually crosses several target journeys:

```text
prepare a manual run
  -> start the run outside Scopecat
  -> monitor running measurement
  -> record run facts
  -> browse and review completed results
  -> share selected results, continue calibration, or reproduce from reference
```

Scopecat intentionally validates smaller boundaries around preparation,
monitoring, recording, review, sharing, calibration continuation, and reference
rerun instead of claiming a single umbrella measurement lifecycle.

## Active Journeys

| ID | Journey | Goal | Current-State Pressure | Related Use Cases | Capabilities | Maturity Posture | Next Decision |
| --- | --- | --- | --- | --- | --- | --- | --- |
| JNY-001 | Share A Selected Measurement | Export a selected complete-enough Measurement Record to a reviewable handoff package and let a receiving user preview and import it explicitly. | Users manually copy run data, sidecars, notebooks, reports, and folders; identity, missing context, and transformed-versus-primary data are easy to lose. | UC-003, UC-004, UC-006, JNY-001-SMOKE | CAP-001, CAP-002 | Production vertical slice backbone with engineering-prototype segments. | Decide whether to harden production readiness, batch export, linked-context payload follow-up, or a different product fork. |
| JNY-002 | Prepare A Manual Run | Review selected parameter, code, environment, setup, and prior context before a manual run without granting Scopecat run-start or hardware-control authority. | Users inspect scattered parameter files, code folders, environment state, setup notes, and notebooks manually before running. | UC-CAND-002; supported by UC-CAND-003 and UC-CAND-006; setup binding supporting workflow | CAP-003, CAP-004, CAP-005, CAP-001 context links | Discovery. | Decide whether prepared-run context review becomes a live route owner with acknowledgement or deferral semantics. |
| JNY-003 | Recover Or Continue Calibration Work | Recover or continue multi-step calibration work using reviewable fit, evidence, action, and continuation state. | Users recover failed fits, retry decisions, and downstream blocking from scattered notebook state. | UC-CAND-005; supported by UC-CAND-006 | CAND-001, CAP-003, CAP-001 context links | Discovery and scenario evidence. | Decide whether repeated calibration continuation needs stable review state and action recording beyond one scenario. |
| JNY-004 | Monitor A Running Measurement | Inspect progress and useful partial data from long-running measurements before the full run finishes. | Users inspect running work through scripts, partial files, or live plotting tools while completeness is ambiguous. | UC-CAND-004 | CAP-006, CAP-001 | Discovery. | Validate lifecycle, progress, and partial-data event recording without scan-control authority. |
| JNY-007 | Record Runs | Record existing, external, legacy-backed, adapter-authored, or manually declared run facts as a local Measurement Record without replacing the producing system. | Users preserve measurement facts by copying files, preserving notes, or relying on folder conventions; durable identity, source posture, and primary-data readiness are mixed together. | UC-001, UC-002 | CAP-001 | Engineering prototype. | Decide which first user-facing recording route should own UX beyond Measurement Records scaffolding. |
| JNY-008 | Browse And Review Completed Results | Browse, filter, plot, and review completed or near-completed results before handoff, comparison, calibration continuation, or rerun preparation. | Users reopen results through folders, notebooks, plots, reports, sidecars, and memory before deciding whether a result is ready. | UC-CAND-007; supported by UC-CAND-006 | CAP-001, CAP-005, CAP-002 | Candidate journey with related prototype pressure. | Choose the first live records browser, plotter, readiness-review, or narrow post-run review route. |
| JNY-009 | Reproduce Or Rerun From A Reference | Start from a known-good or notable reference, compare current context against it, and prepare enough reviewed context to rerun or investigate differences. | Users compare against references by reopening files, notebooks, setup notes, copied folders, and memory. | UC-CAND-003, UC-CAND-006 | CAP-001, CAP-003, CAP-004, CAP-005 | Discovery. | Choose whether the first concrete step is reference selection, declared context comparison, selected-code comparison, workspace materialization, or rerun preparation. |

## Use Case Index

| ID | Level | Name | Supports Journey | Capability Areas | Current Maturity | Validation Owner |
| --- | --- | --- | --- | --- | --- | --- |
| UC-001 | Use case | Adopt-first recording makes a legacy or external run visible locally. | JNY-007 | CAP-001 | Engineering prototype | [`workflow-validation-map.md`](../engineering/workflow-validation-map.md) |
| UC-002 | Use case | Import-ready recording makes reviewed primary data durable locally. | JNY-007 | CAP-001 | Engineering prototype | [`workflow-validation-map.md`](../engineering/workflow-validation-map.md) |
| UC-003 | Workflow segment | Package-writer input becomes a local handoff package for review. | JNY-001 | CAP-002 | Engineering prototype | [`workflow-validation-map.md`](../engineering/workflow-validation-map.md) |
| UC-004 | Workflow segment | Handoff package is received and imported into local storage. | JNY-001 | CAP-001, CAP-002 | Engineering prototype | [`workflow-validation-map.md`](../engineering/workflow-validation-map.md) |
| UC-006 | Workflow segment | Selected stored Measurement Record becomes a handoff package. | JNY-001 | CAP-001, CAP-002 | Production vertical slice segment | [`workflow-validation-map.md`](../engineering/workflow-validation-map.md) |
| JNY-001-SMOKE | Workflow smoke path | Share selected measurement vertical-slice smoke path. | JNY-001 | CAP-001, CAP-002 | Production vertical slice | [`workflow-validation-map.md`](../engineering/workflow-validation-map.md) |
| UC-CAND-002 | Candidate use case | Prepared-run context review and acknowledgement. | JNY-002 | CAP-001, CAP-003, CAP-004, CAP-005 | Discovery | [`workflow-validation-map.md`](../engineering/workflow-validation-map.md) |
| UC-CAND-003 | Candidate use case | First promoted experiment-code context step. | JNY-009; supports JNY-002 | CAP-004, CAP-005 | Discovery | [`workflow-validation-map.md`](../engineering/workflow-validation-map.md) |
| UC-CAND-004 | Candidate use case | Lifecycle, progress, and partial-data event recording for running measurement inspection. | JNY-004 | CAP-001, CAP-006 | Discovery | [`workflow-validation-map.md`](../engineering/workflow-validation-map.md) |
| UC-CAND-005 | Candidate use case | Calibration continuation use case with stable review state and action recording. | JNY-003 | CAND-001, CAP-001, CAP-003 | Discovery | [`workflow-validation-map.md`](../engineering/workflow-validation-map.md) |
| UC-CAND-006 | Candidate use case | Declared context comparison against a selected reference. | JNY-009; supports JNY-002, JNY-003, JNY-008 | CAP-001, CAP-003, CAP-005 | Discovery | [`workflow-validation-map.md`](../engineering/workflow-validation-map.md) |
| UC-CAND-007 | Candidate use case | Post-run results browsing, plotting, and readiness review. | JNY-008 | CAP-001, CAP-002, CAP-005 | Discovery | [`workflow-validation-map.md`](../engineering/workflow-validation-map.md) |

## Supporting Workflows

| Workflow | Former ID | Supports | Current Status | Promotion Rule |
| --- | --- | --- | --- | --- |
| Experiment Code Context Recovery And Reuse | JNY-005, retired | JNY-001, JNY-002, JNY-003, JNY-009 | Supporting workflow and CAP-005 discovery area. | Promote only through a consuming use case such as recording, comparing, materializing, observing editable folders, preparing reruns, or GUI review. |
| Selected Reference Comparison | JNY-006, retired | JNY-001 later, JNY-002, JNY-003, JNY-008, JNY-009 | Supporting workflow represented by UC-CAND-006. | Promote only if comparison itself becomes an independent user job with a stable trigger, result, product surface, and acceptance criteria. |
| Setup Binding Snapshot | None | JNY-001 context later, JNY-002, JNY-009 | Supporting workflow folded into prepared-run context and reference-rerun pressure. | Promote only if setup binding has an independently useful user goal beyond prepared-run or reference context review. |

## Deferred Umbrella Journey

`Start And Complete A Measurement` remains deferred. It would couple parameter
apply, code execution, environment readiness, monitoring, result recording,
failure recovery, final review, and handoff before narrower workflows earn
those boundaries.

Promotion requires a named use case that proves manual review, explicit
run-start authority, execution boundary, monitoring, result recording, post-run
review, and recovery expectations together.

## Update Rule

Update this index when a branch:

- adds, renames, retires, splits, or merges a `JNY-*`, `UC-*`, or `UC-CAND-*`
  owner;
- changes which journey a use case, candidate use case, or supporting workflow
  belongs to;
- changes the capability IDs, maturity posture, or next product decision for a
  journey or use case;
- promotes a supporting workflow into a target journey.

Do not use this index for detailed validation evidence, implementation
entrypoints, tests, fixtures, package formats, ADR rationale, or active task
queues.
