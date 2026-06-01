# Calibration Review Action Recording Validation Plan

## Status

Planned workflow-action recording slice.

This is not an ADR, GUI contract, notebook execution contract, action API,
runner, executor, storage architecture, or shared action schema.

## Question

Can Scopecat record explicit user-declared choices against labels exposed by
the calibration continuation review surface without executing those choices or
mutating workflow state?

## Boundary

Validate review-only action recording with:

- a prior calibration continuation review surface summary;
- action events that reference existing surface action labels by source,
  target, and label;
- actor, timestamp, reason, and event identity;
- event posture fixed to review/audit intent only.

Keep out of scope:

- action execution;
- GUI events or callbacks;
- notebook cell execution;
- measurement payload reads;
- fitting, calibration, measurement, or child-slice execution;
- storage mutation;
- hardware control;
- parameter write-back;
- automatic run start;
- shared action schema.

## Fixture Shape

Use one repository-safe synthetic fixture with:

- one event against a step review-card label;
- one event against a backbone context-finding label;
- UTC timestamps, actor references, and reasons;
- no commands, callbacks, notebook cells, or executable payloads.

## Expected Result

The candidate should validate each event against the review surface action
palette, return ordered recorded events and counts by source, and reject
unavailable labels, duplicate events, executable fields, execution states, or
positive workflow-action claims.
