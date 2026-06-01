# Calibration-Derived Parameter State Measurement Context Validation Result

## Status

Implementation candidate validated.

This result validates one narrow route-level composition slice:
**Calibration-Derived Parameter State Measurement Context**.

It is not an ADR, final shared relation graph, shared calibration/parameter/
measurement schema, runner, executor, hardware-control contract, storage
architecture, or GUI design.

## Inputs

- [`calibration-step-observation-link-validation-result.md`](calibration-step-observation-link-validation-result.md)
- [`calibration-accepted-write-handoff-validation-result.md`](calibration-accepted-write-handoff-validation-result.md)
- [`../parameter-state/calibration-parameter-state-intake-validation-result.md`](../parameter-state/calibration-parameter-state-intake-validation-result.md)
- [`../parameter-state/calibration-parameter-state-storage-validation-result.md`](../parameter-state/calibration-parameter-state-storage-validation-result.md)
- [`../parameter-state/prepared-run-source-agnostic-parameter-state-consumption-validation-result.md`](../parameter-state/prepared-run-source-agnostic-parameter-state-consumption-validation-result.md)
- [`../measurement-context/measurement-context-link-validation-result.md`](../measurement-context/measurement-context-link-validation-result.md)
- [`calibration-derived-parameter-state-measurement-context-validation-plan.md`](calibration-derived-parameter-state-measurement-context-validation-plan.md)
- `tests/fixtures/calibration_derived_parameter_state_measurement_context/basic_chain/`
- `implementation_candidates/calibration_derived_parameter_state_measurement_context/`

## Validated Boundary

The fixture and side-effect-free implementation candidate validate the main
cross-route workflow trunk:

- a calibration observation remains linked to the measurement record used as
  fit input;
- an accepted calibration write handoff preserves the calibration step,
  observation measurement record, base parameter-state identity, lineage, path,
  and `not_applied` state;
- parameter-state intake consumes that handoff through explicit
  parameter-state review and produces a managed snapshot;
- the stored snapshot preserves calibration handoff provenance;
- a later prepared-run context selects that stored snapshot as required
  parameter context;
- the later measurement record links the same selected snapshot as optional
  reference-only run-start context;
- review findings from child summaries are carried into the composition
  without invalidating measurement primary data.

The implementation candidate checks policy claims, calibration observation to
handoff continuity, handoff to parameter-state intake continuity, intake to
stored snapshot continuity, stored snapshot to prepared-run selection
continuity, and prepared-run selection to measurement-record context-link
continuity.

## What The Summary Can Answer

The candidate summary can answer:

- which calibration observation and measurement produced the accepted handoff;
- which base parameter state, lineage, and parameter path were changed;
- which managed parameter-state snapshot resulted;
- whether the snapshot was stored as calibration-derived state;
- which prepared run selected the snapshot;
- which later measurement record linked the same snapshot as run-start
  parameter context;
- why this route composition does not imply payload reads, fitting,
  calibration execution, hardware apply, run start, compatibility output,
  relation-graph traversal, or a shared schema.

The expected-output fixture is an `internal_validation_summary` repository
artifact. This slice does not validate portable/export review artifact
behavior.

## Not Earned

This validation does not earn:

- final shared relation graph;
- shared calibration, parameter-state, prepared-run, or measurement schema;
- measurement payload reads;
- fitting, calibration, measurement, or child-slice execution;
- storage mutation or fresh storage reads;
- hardware apply, hardware control, or current instrument state;
- parameter write-back;
- compatibility artifact authority;
- automatic run start;
- GUI workflow.

## Validation

- `uv run python -m unittest tests.test_calibration_derived_parameter_state_measurement_context_fixture tests.test_calibration_derived_parameter_state_measurement_context_summary_candidate`

## Slice Recommendation

Keep this as the main trunk composition proof. The next useful work is route
consolidation that names this flow as the current calibration-to-measurement
backbone, or a narrower workflow-action slice only if users need to record
explicit review actions between these validated summaries.
