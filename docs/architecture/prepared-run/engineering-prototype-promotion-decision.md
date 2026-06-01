# Prepared Run Engineering Prototype Promotion Decision

## Status

Engineering promotion decision, not an ADR.

This is the canonical prepared-run implementation-boundary note for the
accepted local context-construction and review surfaces. Update this file when
an accepted prepared-run boundary or next decision gate changes. Keep live API
syntax in
[`../../../scopecat/prepared_run/README.md`](../../../scopecat/prepared_run/README.md).

Artifact posture: `internal_validation_summary`. This note is internal project
memory. It creates no portable package output, public contract, public SDK, or
new redaction rule.

## Decision

Promote the stable prepared-run context-construction and manual review
surfaces from historical implementation-candidate evidence into
`scopecat/prepared_run/`.

The accepted local chain is:

```text
declared family-owned context records
  -> PreparedRunContextRequest
  -> compose_prepared_run_context(...)
  -> PreparedRunContextResult
  -> local prepared-run context summary
  -> explicit prior prepared-run review summaries
  -> PreparedRunReviewGateRequest
  -> compose_prepared_run_review_gate(...)
  -> PreparedRunReviewGateResult
  -> local review_summary projection
  -> optional PreparedRunAcknowledgementReviewRequest
  -> local acknowledgement/continuation review_summary projection
  -> local PreparedRunReviewViewStateRequest
  -> local review view-state projection
```

Raw-dictionary adapters remain available for current fixture and edge use:
`build_prepared_run_context_summary(...)` and
`build_prepared_run_review_gate_summary(...)`.

This accepted integration step keeps prepared-run as the consumer of prior
evidence: typed `EnvironmentOperationReview` objects from
`scopecat.environment_operation` can be projected into the optional
environment-operation evidence slot by
`project_environment_operation_review_for_prepared_run(...)`. The projection
adds only the prepared-run context reference required for continuity checks and
does not move manager semantics or execution review into prepared-run.

## Accepted Baseline

The promoted baseline includes:

- the route-local `scopecat/prepared_run/` module boundary;
- typed local request/result objects for prepared-run context construction;
- typed local request/result objects for the review gate;
- a raw-dictionary adapter at the edge;
- declared family-owned context records grouped by reference;
- selected-context reference validation without accepting unresolved selected
  IDs;
- selected managed-code-version and editable-workspace-observation alignment;
- manual-run target alignment to selected measurement intent;
- missing required context and workspace-observation review findings without
  run-blocking, workspace-usability, or readiness claims;
- explicit prior-summary inputs only;
- read-only review-summary composition;
- prepared-run-context continuity validation across child summaries;
- review item aggregation for required context, parameter state, scope
  alignment, workspace context, environment review, and optional
  environment-operation review evidence;
- optional typed environment-operation review evidence projected from the
  accepted `scopecat.environment_operation` review object;
- aggregated child findings with source areas and preserved non-claims;
- missing required context precedence as `blocked_by_required_context`;
- clear inputs producing `ready_for_manual_review`;
- flagged non-required areas producing `manual_pre_run_review_needed`;
- optional local acknowledgement review over selected gate review items and
  findings;
- acknowledgement continuation state that can record non-required review items
  as handled for manual continuation while keeping required-context blocks
  blocked;
- deterministic local view-state projection over the gate and optional
  acknowledgement output;
- header state, review item rows, finding rows, acknowledgement state,
  label-only next actions, and attention/non-claim notices for manual review
  presentation;
- local `review_summary` / local review projection posture.

## Explicit Non-Promotions

This decision does not promote:

- all prepared-run or run-context implementation candidates;
- a shared universal run-context schema;
- producer-side template semantics, adapter parsing, automatic context
  discovery, or catalog discovery;
- parameter-state storage, source-agnostic parameter-state consumption, or
  parameter write-back;
- approval, GUI component behavior, or GUI persistence behavior;
- runtime readiness, run permission, run safety, restore behavior, scheduler
  behavior, automatic run start, or hardware control;
- dependency resolution, dependency sync, package installation, runtime
  probing, environment operation execution, or verification that an environment
  is synchronized;
- code import, selected-code execution, notebook execution, or generated
  artifact regeneration;
- action execution from view-state labels;
- portable/export artifacts or public documentation output.

## Discovery Candidate Posture

`implementation_candidates/prepared_run_context/` and
`implementation_candidates/prepared_run_review_gate/` remain historical
validation evidence. They are no longer the live implementation owners for the
accepted prepared-run context and review-gate behavior. Do not broaden those
candidates to accumulate new prepared-run behavior. Future changes to accepted
prepared-run behavior should happen in `scopecat/prepared_run/` with focused
tests and only the docs needed to keep this boundary current.

Other prepared-run implementation candidates remain candidate-only evidence
unless a later decision promotes a separately scoped boundary.

## Next Decision Gate

Do not continue by promoting the whole prepared-run route. The next engineering
phase should choose one explicit path:

- GUI component integration over the accepted view-state data;
- a producer-side preparation-template or adapter-normalized context-ref
  boundary, if required inputs need an owned source.

Each path needs its own non-claims before it can add run-start authority,
runtime readiness, parameter writes, hardware control, or portable/export
behavior.
