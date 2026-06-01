# Prepared-Run Source-Agnostic Parameter-State Review Chain Validation Plan

## Status

Validation plan, not an ADR.

This plan defines a thin compatibility slice for proving that source-agnostic
prepared-run parameter-state consumption can reuse the existing prepared-run
parameter-state gate and scope-alignment candidates. It does not accept a new
gate schema, new scope schema, fresh storage reads, catalog discovery,
parameter write-back, compatibility output, hardware control, run-start
permission, GUI behavior, or shared domain model extraction.

## Source Material

This slice follows:

- [`prepared-run-source-agnostic-parameter-state-consumption-validation-result.md`](prepared-run-source-agnostic-parameter-state-consumption-validation-result.md)
- [`prepared-run-parameter-state-gate-validation-result.md`](prepared-run-parameter-state-gate-validation-result.md)
- [`prepared-run-scope-alignment-validation-result.md`](prepared-run-scope-alignment-validation-result.md)

The source-agnostic consumption summary intentionally preserves the same core
shape as the older prepared-run parameter-state consumption summary. This
slice tests whether downstream gate and scope review candidates can consume
that shape unchanged.

First fixture:

- `tests/fixtures/prepared_run_source_agnostic_parameter_state_review_chain/basic_chain/`

## Validation Question

Can the existing prepared-run parameter-state gate and scope-alignment
projection consume source-agnostic prepared-run parameter-state consumption
facts, proving that calibration-derived parameter state can reach manual
pre-run review without a new gate schema or new scope schema?

## Evidence Pressure

The current path is:

- calibration accepted-write handoff;
- parameter-state intake;
- calibration-derived storage;
- source-agnostic read view;
- prepared-run source-agnostic consumption.

The next question is not another abstraction. The next question is whether the
existing manual pre-run review stack already accepts this shape.

## First Fixture Shape

The first fixture should include:

- one source-agnostic prepared-run parameter-state consumption summary selecting
  a calibration-derived state;
- one existing parameter-state gate input using that summary unchanged;
- one existing scope-alignment input using that summary unchanged;
- setup-binding facts sufficient to surface partial target coverage for `cAB`;
- expected output proving the gate is ready while scope alignment needs review.

The fixture should not include:

- new gate or scope schemas;
- filesystem reads or catalog discovery;
- parameter writes or compatibility output;
- hardware state, hardware writes, or instrument logs;
- environment sync, code import, code execution, or run-start permission;
- GUI operations.

## Expected Output

Expected review output should let a reviewer answer:

- whether existing gate logic accepted source-agnostic consumption unchanged;
- whether existing scope-alignment logic accepted source-agnostic consumption
  unchanged;
- whether the selected calibration-derived state reached manual pre-run review;
- which gate decision and scope-alignment classification resulted;
- which downstream review findings remain;
- why the composition does not imply new schemas, fresh storage reads, catalog
  discovery, parameter write-back, compatibility output, hardware control, or
  run-start permission.

## Out Of Scope

This plan does not earn:

- new gate schema;
- new scope-alignment schema;
- fresh storage read;
- catalog or index discovery;
- parameter write-back or compatibility output;
- hardware control or current instrument state;
- automatic run start;
- run execution or runnable readiness;
- GUI behavior;
- shared domain model extraction.

## Slice Recommendation

Stop this slice when reuse is proven. If the existing gate and scope alignment
consume source-agnostic facts unchanged, the next useful work should be higher
in the prepared-run review stack rather than another parameter-state gate
variant.
