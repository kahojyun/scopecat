# Calibration Accepted Write Handoff Validation Result

## Status

Implementation candidate validated.

This result validates one narrow calibration workflow slice:
**Calibration Accepted Write Handoff**.

It is not a final calibration step schema, parameter-state schema, relation
graph, write-back contract, hardware-control contract, storage model,
scheduler, workflow DAG, or GUI design.

## Fixture

Fixture:
[`../../tests/fixtures/calibration_accepted_write_handoff/basic_handoff/`](../../../../tests/fixtures/calibration_accepted_write_handoff/basic_handoff)

Implementation candidate:
[`../../implementation_candidates/calibration_accepted_write_handoff/`](../../../../implementation_candidates/calibration_accepted_write_handoff)

The fixture records one qA Rabi calibration step record with a resolved
parameter-state context. An accepted proposed write targets one parameter path
in that base state and is shaped as a parameter-state management draft/review
request.

## What This Earned

The implementation candidate shows that a side-effect-free summary can:

- require calibration writes to be explicitly accepted for parameter-state
  handoff before handoff;
- keep accepted handoff writes in `apply_state: not_applied`;
- require the before-summary parameter context to be linked by the calibration
  step record;
- require the target lineage, path, unit, and old value to match the base
  parameter-state context;
- shape a parameter-state management draft/review request with old/new diff
  facts;
- leave durable history, review acceptance, draft creation, and committed
  state creation to the parameter-state route;
- surface blocked handoff requests as review findings rather than automatic
  invalidation, write-back, rollback, or hardware apply behavior;
- reject fixture claims that cross into parameter-state commit, compatibility
  output, hardware control, rollback, measurement payload reads, fitting,
  calibration execution, scheduling, or shared parameter schema behavior.

## Boundary

This slice validates accepted calibration write handoff only.

It does not:

- define final calibration step, parameter-state, relation graph, lifecycle,
  storage, or package schemas;
- create parameter-state drafts;
- accept reviewable diffs or create committed parameter-state snapshots;
- produce external compatibility output;
- apply writes to hardware or parameter stores;
- define rollback behavior;
- read measurement payloads or primary measurement data;
- run fitting, scoring, model selection, or scientific validity checks;
- execute calibration code or measurement code;
- decide continuation, retry, skip, refit, or remeasurement;
- control hardware;
- schedule work;
- recursively traverse adjacent records;
- define a GUI workflow.

## Result

Calibration can own the decision that a proposed write is ready to hand to
parameter-state management without becoming the parameter-state authority.

The handoff carries enough structured context for parameter-state management to
start a draft/review flow: base state, lineage, parameter path, old value, and
candidate value. It still creates no draft, no review acceptance, no committed
state, no compatibility output, and no hardware apply.

## Follow-Up

Stop this slice at parameter-state route handoff unless a concrete workflow
needs stronger behavior.

Likely follow-up slices should stay separate:

- parameter-state intake from accepted calibration handoff, owned by the
  parameter-state route;
- compatibility-output planning from accepted committed parameter state;
- hardware apply recording only after hardware-control authority is separately
  validated;
- rollback only after an actual apply/commit workflow exists.
