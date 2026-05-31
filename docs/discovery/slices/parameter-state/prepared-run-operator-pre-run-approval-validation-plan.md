# Prepared-Run Operator Pre-Run Approval Validation Plan

## Status

Validation plan, not an ADR.

This plan defines a narrow operator decision record over an
acknowledgement-aware manual pre-run review summary. It does not accept
automatic run start, hardware control, parameter write-back, compatibility
output, dependency operations, fresh reads, setup or workspace mutation,
environment operation, code execution, durable storage, GUI behavior, managed
runner behavior, or a shared approval schema.

## Source Material

This slice follows:

- [`prepared-run-acknowledgement-aware-review-gate-validation-result.md`](prepared-run-acknowledgement-aware-review-gate-validation-result.md)
- [`prepared-run-partial-target-acknowledgement-validation-result.md`](prepared-run-partial-target-acknowledgement-validation-result.md)

The acknowledgement-aware review gate stops at
`ready_for_operator_pre_run_decision`. This slice records the operator decision
over that review summary and keeps execution in a later explicit workflow.

First fixture:

- `tests/fixtures/prepared_run_operator_pre_run_approval/basic_approval/`

## Validation Question

Can an operator approval, rejection, or deferral be recorded against the exact
reviewed prepared-run context, measurement, and parameter-state snapshot
without starting a run or mutating any context?

## First Fixture Shape

The first fixture should include:

- one acknowledgement-aware review-gate summary in
  `ready_for_operator_pre_run_decision`;
- one operator approval decision bound to the review gate, prepared-run
  context, measurement, and selected parameter-state snapshot;
- operator role, decision timestamp, and rationale;
- expected output preserving review facts and recording decision effects as
  non-executing.

The fixture should not include:

- process execution, hardware control, or instrument state;
- parameter write-back or compatibility output;
- dependency operations or environment sync;
- fresh storage, workspace, environment, or hardware observation;
- durable storage writes;
- GUI interaction contracts.

## Expected Output

Expected approval output should let a reviewer answer:

- which review summary the decision applies to;
- which prepared-run context, measurement, and parameter-state snapshot were
  approved;
- whether the operator approved, rejected, or deferred;
- what rationale was recorded;
- which prior review facts are carried forward;
- why no run, hardware, parameter, compatibility, storage, dependency, or GUI
  effect occurred.

## Out Of Scope

This plan does not earn:

- automatic run start;
- hardware control or current instrument state;
- parameter write-back;
- compatibility output;
- dependency resolution, sync, package installation, or runtime probing;
- fresh storage, workspace, environment, or hardware observation;
- setup or workspace mutation;
- environment operation;
- code import or execution;
- durable storage;
- GUI behavior;
- managed runner behavior;
- shared approval schema.
