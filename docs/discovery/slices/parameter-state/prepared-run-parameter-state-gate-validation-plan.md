# Prepared Run Parameter State Gate Validation Plan

## Status

Validation plan for an implementation candidate.

This is not an ADR, final storage architecture, catalog/index contract,
parameter write-back contract, hardware-control contract, run-start contract,
executor, GUI design, or shared gate schema.

## User Job

Given a prepared-run parameter-state consumption summary, classify the selected
parameter-state context for manual run review without starting a run, writing
parameters, reading storage again, discovering catalogs, syncing environments,
or controlling hardware.

## Boundary To Validate

- gate authority is a declared prepared-run parameter review policy;
- input is one prepared-run parameter-state consumption summary;
- the gate classifies only parameter-state context review state;
- ready consumption with enough trusted entries becomes
  `ready_for_manual_run_review`;
- consumption findings become `needs_parameter_review`;
- unavailable required parameter context becomes
  `blocked_by_required_parameter_context`;
- trusted-entry count, state identity, and consumption classification are
  projected as gate inputs;
- no automatic run start, parameter write-back, hardware control, fresh storage
  read, catalog discovery, storage mutation, environment sync, code execution,
  GUI behavior, or shared gate schema is accepted.

## Fixture

Use `tests/fixtures/prepared_run_parameter_state_gate/basic_gate/`.

The fixture is repository-safe synthetic data. It consumes compact summary
facts from the prepared-run parameter-state consumption slice. The validation
summary posture is `internal_validation_summary`.

## Validation Steps

1. Validate fixture JSON and expected summary shape.
2. Validate gate policy and request shape.
3. Validate consumed summary side-effect non-claims.
4. Classify a ready consumed parameter state for manual run review.
5. Carry consumption findings into gate findings.
6. Block unavailable required parameter context.
7. Surface insufficient trusted entries and state-id mismatches as review
   findings.

## Tests

- `tests/test_prepared_run_parameter_state_gate_fixture.py`
- `tests/test_prepared_run_parameter_state_gate_summary_candidate.py`

Run:

```bash
uv run python -m unittest tests.test_prepared_run_parameter_state_gate_fixture tests.test_prepared_run_parameter_state_gate_summary_candidate
uv run python -m unittest discover -s tests
uv run ruff check .
uv run ruff format --check .
```
