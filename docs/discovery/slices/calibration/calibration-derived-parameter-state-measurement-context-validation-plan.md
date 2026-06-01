# Calibration-Derived Parameter State Measurement Context Validation Plan

## Status

Planned route-level composition slice.

This is not an ADR, final relation graph, final shared domain model, runner,
executor, hardware-control contract, GUI design, or storage architecture.

## Question

Can existing validated summaries express the main workflow trunk where a
calibration-derived parameter-state snapshot becomes the selected parameter
context for a later measurement record?

## Boundary

Validate only declared-summary continuity:

- calibration observation measurement record to accepted calibration write
  handoff;
- accepted handoff to parameter-state intake;
- parameter-state intake to stored calibration-derived snapshot;
- stored snapshot to prepared-run selected parameter context;
- prepared-run selected parameter context to the later measurement record's
  reference-only context link.

Keep out of scope:

- measurement payload reads;
- fit, calibration, or measurement execution;
- child-slice execution;
- storage mutation or fresh storage reads;
- hardware apply, hardware control, or current instrument state;
- parameter write-back;
- compatibility output;
- automatic run start;
- recursive relation-graph traversal;
- GUI workflow;
- shared calibration, parameter-state, prepared-run, or measurement schema.

## Fixture Shape

Use one repository-safe synthetic fixture with:

- a calibration observation summary pointing to the measurement used for fit
  input;
- an accepted write handoff summary that remains `not_applied`;
- a parameter-state intake summary that preserves handoff, base-state, lineage,
  and accepted path continuity;
- a stored parameter-state summary marked `calibration_handoff`;
- a prepared-run context summary selecting the calibration-derived state;
- a prepared-run parameter-state consumption summary for the same state;
- a measurement context-link summary where the later measurement record links
  the same state as optional `run_start_context`.

## Expected Result

The candidate should produce a read-only continuity summary proving the
selected managed parameter-state snapshot is the stable context identity across
calibration, parameter-state management, prepared-run review, and measurement
recording.

Review findings from child summaries should make the composition need review
without invalidating measurement primary data or claiming workflow execution.
