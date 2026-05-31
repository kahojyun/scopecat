# Prepared-Run Partial Target Acknowledgement Validation Plan

## Status

Validation plan, not an ADR.

This plan defines a narrow local acknowledgement slice for the known
prepared-run `parameter_lineage_partial_target_coverage` review finding. It
does not accept parameter invalidation, parameter write-back, compatibility
output, hardware control, run-start permission, setup mutation, scope repair,
GUI behavior, or a shared acknowledgement schema.

## Source Material

This slice follows:

- [`prepared-run-source-agnostic-parameter-state-review-chain-validation-result.md`](prepared-run-source-agnostic-parameter-state-review-chain-validation-result.md)
- [`prepared-run-scope-alignment-validation-result.md`](prepared-run-scope-alignment-validation-result.md)

The review chain already proves that the calibration-derived parameter state
can reach existing manual pre-run gate and scope review. It also preserves the
partial target-coverage finding for `cAB`. This slice tests only whether a
local user acknowledgement can bind to that exact finding and leave the rest of
the review/execution boundary untouched.

First fixture:

- `tests/fixtures/prepared_run_partial_target_acknowledgement/basic_acknowledgement/`

## Validation Question

Can a user acknowledge the exact partial target-coverage review finding for a
prepared-run context and selected parameter-state snapshot while preserving the
original finding basis and without granting execution authority?

## First Fixture Shape

The first fixture should include:

- one source-agnostic parameter-state review-chain summary;
- one user acknowledgement naming the prepared-run context and selected
  parameter-state snapshot;
- exact acknowledgement of the `scope_alignment`
  `parameter_lineage_partial_target_coverage` finding basis;
- explicit side-effect claims showing no parameter invalidation, parameter
  write-back, compatibility output, hardware control, automatic run start,
  scope repair, setup mutation, catalog discovery, or fresh storage read.

The fixture should not include:

- parameter or setup repair behavior;
- compatibility-output generation;
- hardware apply or instrument-state facts;
- run-start approval;
- GUI interaction contracts;
- reusable acknowledgement schema extraction.

## Expected Output

Expected acknowledgement output should let a reviewer answer:

- which prepared-run context and parameter state the acknowledgement applies to;
- which exact finding and target-coverage basis was acknowledged;
- whether any review findings remain visible;
- which downstream gate and scope classifications existed before
  acknowledgement;
- why acknowledgement does not imply parameter invalidation, write-back,
  compatibility output, hardware safety, setup mutation, or run-start
  permission.

## Out Of Scope

This plan does not earn:

- parameter invalidation or scope repair;
- parameter write-back or compatibility output;
- hardware control or current instrument state;
- automatic run start;
- setup mutation;
- fresh storage read or catalog discovery;
- GUI behavior;
- shared acknowledgement schema.
