# Calibration Backbone Context Findings Validation Plan

## Status

Planned route-level findings slice.

This is not an ADR, final relation graph, shared route schema, GUI workflow,
runner, executor, storage architecture, or hardware-control contract.

## Question

Can the validated calibration-derived parameter-state measurement-context
backbone surface missing or mismatched route facts as review findings without
inventing a shared schema, blocking measurement validity, or executing
workflow actions?

## Boundary

Validate review-only findings for degraded route facts:

- missing calibration observation summary;
- accepted write handoff missing or not ready;
- parameter-state intake unavailable or not tied to the accepted handoff;
- stored calibration-derived snapshot unavailable or mismatched;
- prepared run selecting the wrong parameter-state snapshot;
- later measurement record missing the parameter context link or linking a
  different snapshot.

Keep out of scope:

- measurement payload reads;
- fitting, calibration, measurement, or child-slice execution;
- fresh storage reads, catalog discovery, storage repair, or storage mutation;
- hardware apply, hardware control, or current instrument state;
- parameter write-back;
- compatibility output;
- automatic run start;
- relation-graph traversal or repair;
- measurement validity decisions;
- GUI workflow;
- shared calibration, measurement, prepared-run, or parameter-state schema.

## Fixture Shape

Use one repository-safe synthetic fixture with several declared backbone cases:

- a complete ready case;
- blocked cases for missing observation, not-ready handoff, missing
  parameter-state intake, and wrong prepared-run snapshot selection;
- review-only cases for missing measurement context and measurement context
  linked to the wrong snapshot.

## Expected Result

The candidate should produce per-case classifications and review findings.
Blocked upstream continuity findings should not become automatic repair,
retry, remeasurement, or hardware-apply decisions. Measurement context
findings should remain review evidence and should not invalidate primary
measurement data.
