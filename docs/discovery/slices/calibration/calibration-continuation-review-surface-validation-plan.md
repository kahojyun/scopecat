# Calibration Continuation Review Surface Validation Plan

## Status

Planned notebook/CLI consumption slice.

This is not an ADR, GUI design, notebook integration contract, action API,
runner, executor, storage architecture, or shared surface schema.

## Question

Can existing calibration review-state cards, the validated
calibration-derived parameter-state backbone, and backbone context findings be
projected into one notebook/CLI-shaped review surface without rendering a GUI
or executing actions?

## Boundary

Validate a read-only surface summary with:

- route header state;
- step review cards and state counts;
- selected parameter-state backbone context panel;
- missing/partial backbone findings panel;
- labels-only action palette derived from review cards and findings.

Keep out of scope:

- GUI component model or rendering;
- notebook cell execution;
- action execution;
- measurement payload reads;
- fitting, calibration, measurement, or child-slice execution;
- storage mutation;
- hardware control;
- parameter write-back;
- automatic run start;
- shared surface schema.

## Fixture Shape

Use one repository-safe synthetic fixture with:

- one handoff-ready review card;
- one fit-review-needed card;
- one happy-path backbone context summary;
- blocked and review-only backbone findings;
- labels-only action posture.

## Expected Result

The candidate should produce notebook/CLI-shaped summary data that helps a
reviewer see step state, backbone context, and route findings together while
rejecting executable commands, GUI component fields, notebook execution claims,
or required measurement-context validity claims.
