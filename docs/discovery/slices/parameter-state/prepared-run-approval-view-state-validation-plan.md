# Prepared-Run Approval View State Validation Plan

## Status

Validation plan, not an ADR.

This plan defines a read-only view-state projection over the prepared-run
parameter-state review, acknowledgement, and operator approval path. It does
not accept GUI workflow, action execution, automatic run start, hardware
control, parameter write-back, compatibility output, fresh storage reads,
catalog discovery, durable storage, environment operation, code execution,
managed runner behavior, or a shared view schema.

## Source Material

This slice follows:

- [`prepared-run-operator-pre-run-approval-validation-result.md`](prepared-run-operator-pre-run-approval-validation-result.md)
- [`prepared-run-acknowledgement-aware-review-gate-validation-result.md`](prepared-run-acknowledgement-aware-review-gate-validation-result.md)
- [`parameter-compatibility-artifacts-boundary-clarification.md`](parameter-compatibility-artifacts-boundary-clarification.md)

The active route now treats the managed parameter-state snapshot as canonical
parameter context. Compatibility artifacts are omitted unless explicitly
supplied as debug/attachment evidence.

First fixture:

- `tests/fixtures/prepared_run_approval_view_state/basic_view/`

## Validation Question

Can Scopecat present the selected parameter-state snapshot, scope
acknowledgement, operator decision, and remaining findings as read-only view
state without defining GUI behavior or elevating compatibility artifacts to
context?

## First Fixture Shape

The first fixture should include:

- one operator pre-run approval summary;
- one view request bound to approval, review gate, prepared-run context,
  measurement, and selected parameter-state snapshot;
- no debug attachments;
- expected output with parameter-state context, acknowledgement card, operator
  decision card, labels-only actions, and explicit non-effects.

The fixture should not include:

- GUI component or workflow contracts;
- action execution;
- run start, hardware control, or parameter write-back;
- compatibility output or compatibility artifact context;
- storage mutation or fresh observation.

## Expected Output

Expected view output should let a reviewer answer:

- which prepared-run context and measurement are shown;
- which parameter-state snapshot is canonical context;
- which partial target-coverage finding was acknowledged;
- whether the operator approved, rejected, or deferred;
- whether findings remain;
- whether debug attachments were supplied;
- why the projection is read-only and non-executing.

## Out Of Scope

This plan does not earn:

- GUI workflow or component model;
- action execution;
- automatic run start;
- hardware control or current instrument state;
- parameter write-back;
- compatibility output or compatibility artifact context;
- fresh storage read or catalog discovery;
- durable storage;
- environment operation;
- code import or execution;
- managed runner behavior;
- shared view schema.
