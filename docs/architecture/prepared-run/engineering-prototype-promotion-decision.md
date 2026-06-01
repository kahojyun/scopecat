# Prepared Run Engineering Prototype Promotion Decision

## Status

Engineering promotion decision, not an ADR.

This is the canonical prepared-run implementation-boundary note for the first
local review-gate surface. Update this file when an accepted prepared-run
boundary or next decision gate changes. Keep live API syntax in
[`../../../scopecat/prepared_run/README.md`](../../../scopecat/prepared_run/README.md).

Artifact posture: `internal_validation_summary`. This note is internal project
memory. It creates no portable package output, public contract, public SDK, or
new redaction rule.

## Decision

Promote only the stable prepared-run manual review gate from historical
implementation-candidate evidence into `scopecat/prepared_run/`.

The accepted local chain is:

```text
explicit prior prepared-run review summaries
  -> PreparedRunReviewGateRequest
  -> compose_prepared_run_review_gate(...)
  -> PreparedRunReviewGateResult
  -> local review_summary projection
  -> optional PreparedRunAcknowledgementReviewRequest
  -> local acknowledgement/continuation review_summary projection
  -> local PreparedRunReviewViewStateRequest
  -> local review view-state projection
```

The raw-dictionary adapter remains available for current fixture and edge use:
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
- typed local request/result objects for the review gate;
- a raw-dictionary adapter at the edge;
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
- prepared-run context creation or catalog discovery;
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

`implementation_candidates/prepared_run_review_gate/` remains historical
validation evidence. It is no longer the live implementation owner for the
prepared-run review gate. Do not broaden that candidate to accumulate new
prepared-run behavior. Future changes to the accepted review-gate behavior
should happen in `scopecat/prepared_run/` with focused tests and only the docs
needed to keep this boundary current.

Other prepared-run implementation candidates remain candidate-only evidence
unless a later decision promotes a separately scoped boundary.

## Next Decision Gate

Do not continue by promoting the whole prepared-run route. The next engineering
phase should choose one explicit path:

- GUI component integration over the accepted view-state data;
- a separately scoped prepared-run context construction boundary.

Each path needs its own non-claims before it can add run-start authority,
runtime readiness, parameter writes, hardware control, or portable/export
behavior.
