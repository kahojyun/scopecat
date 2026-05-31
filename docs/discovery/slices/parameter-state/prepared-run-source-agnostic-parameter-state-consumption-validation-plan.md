# Prepared-Run Source-Agnostic Parameter-State Consumption Validation Plan

## Status

Validation plan, not an ADR.

This plan defines a narrow prepared-run composition slice that consumes a
source-agnostic parameter-state read-view summary. It does not accept fresh
storage reads, catalog discovery, parameter write-back, hardware control,
run-start permission, execution readiness, GUI behavior, universal provenance
schema, or shared domain model extraction.

## Source Material

This slice follows:

- [`source-agnostic-parameter-state-read-view-validation-result.md`](source-agnostic-parameter-state-read-view-validation-result.md)
- [`prepared-run-parameter-state-consumption-validation-result.md`](prepared-run-parameter-state-consumption-validation-result.md)
- [`../experiment-code/prepared-run-context-validation-result.md`](../experiment-code/prepared-run-context-validation-result.md)

The existing prepared-run consumption slice validates a prepared run consuming
one adapter-shaped storage read-view summary. The source-agnostic read-view
slice now exposes adapter-derived and calibration-derived stored states through
one explicit read projection. This slice tests whether prepared-run review can
consume a selected state from that source-agnostic projection.

First fixture:

- `tests/fixtures/prepared_run_source_agnostic_parameter_state_consumption/basic_consumption/`

## Validation Question

Can a prepared-run context select one parameter state from a source-agnostic
read-view summary, project trusted entries and typed provenance for review, and
carry selected-state read findings without re-reading storage, discovering a
catalog, writing parameters, applying hardware state, or granting run-start
permission?

## Evidence Pressure

The calibration-to-parameter-state path now reaches storage and a
source-agnostic read projection. The prepared-run route should be able to use
that calibration-derived state without depending on the older adapter-only
read view. This fixture keeps the pressure narrow:

- one prepared-run context selects `param-state-0008`;
- one source-agnostic read-view summary contains both adapter-derived and
  calibration-derived states;
- the composition selects only the calibration-derived state;
- typed calibration provenance is carried for review;
- no storage read, catalog discovery, write-back, hardware control, execution,
  or GUI behavior is accepted.

## First Fixture Shape

The first fixture should include:

- one declared prepared-run context summary;
- one selected `parameter_state` context ref with role `calibrated_values`;
- one source-agnostic parameter-state read-view summary;
- one consumption request naming the expected state id;
- expected output with selected state facts, trusted entries, typed provenance,
  storage read facts, review findings, and attention states.

The fixture should not include:

- filesystem reads or catalog discovery;
- parameter writes or compatibility output;
- hardware state, hardware writes, or instrument logs;
- environment sync, code import, code execution, or run-start permission;
- GUI operations.

## Expected Output

Expected review output should let a reviewer answer:

- which prepared-run context is consuming parameter-state facts;
- which selected parameter context is expected;
- which source-agnostic stored state backs that context;
- whether the selected state is adapter-derived or calibration-derived;
- which trusted entries are visible for run-preparation review;
- which typed provenance payload is carried;
- which manifest and receipt facts were previously observed;
- why composition does not imply fresh storage read, catalog discovery,
  parameter write-back, hardware state, execution readiness, or run-start
  permission.

## Out Of Scope

This plan does not earn:

- fresh storage read;
- catalog or index discovery;
- parameter write-back or compatibility output;
- hardware control or current instrument state;
- automatic run blocking;
- run execution or runnable readiness;
- GUI behavior;
- universal provenance schema;
- shared parameter or run-context domain model.

## Slice Recommendation

Stop this slice at prepared-run consumption of one selected source-agnostic
stored parameter state. Broader prepared-run gates, compatibility output, and
hardware apply should remain separate slices.
