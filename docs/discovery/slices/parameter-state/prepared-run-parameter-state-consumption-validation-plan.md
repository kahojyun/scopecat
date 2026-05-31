# Prepared Run Parameter State Consumption Validation Plan

## Status

Validation plan for an implementation candidate.

This is not an ADR, final storage architecture, catalog/index contract,
parameter write-back contract, hardware-control contract, executor, GUI design,
or shared domain model.

## User Job

Given a prepared-run context summary and an explicit stored parameter-state
read-view summary, confirm that the prepared-run selected parameter-state
context is backed by the read-view state and expose trusted entries for local
run-preparation review without reading storage again, discovering catalogs,
writing parameters, or controlling hardware.

## Boundary To Validate

- composition authority is a prepared-run parameter-state reference;
- prepared context facts come from a declared prepared-run context summary;
- parameter state facts come from one explicit storage read-view summary;
- the selected prepared-run `parameter_state` context role is matched to the
  read-view state identity;
- trusted entries, provenance, and storage read facts are projected for review;
- read-view findings and selected-context mismatches are carried as review
  findings;
- no fresh storage read, catalog discovery, storage mutation, parameter
  write-back, hardware control, setup mutation, environment sync, code
  execution, GUI behavior, shared parameter schema, or shared run-context
  schema is accepted.

## Fixture

Use `tests/fixtures/prepared_run_parameter_state_consumption/basic_consumption/`.

The fixture is repository-safe synthetic data. It composes a compact declared
prepared-run context summary with the parameter-state storage read-view summary
facts from the explicit read-view slice. The validation summary posture is
`internal_validation_summary`.

## Validation Steps

1. Validate fixture JSON and expected summary shape.
2. Validate policy and side-effect non-claims.
3. Validate prepared-run summary non-claims.
4. Validate parameter-state read-view summary non-claims and trusted-entry
   consistency.
5. Match the prepared-run selected parameter context to the explicit read-view
   state identity.
6. Project trusted entries, provenance, and storage read facts.
7. Surface mismatches, unavailable selected context, or read-view findings as
   review findings rather than hardware or execution decisions.

## Tests

- `tests/test_prepared_run_parameter_state_consumption_fixture.py`
- `tests/test_prepared_run_parameter_state_consumption_summary_candidate.py`

Run:

```bash
uv run python -m unittest tests.test_prepared_run_parameter_state_consumption_fixture tests.test_prepared_run_parameter_state_consumption_summary_candidate
uv run python -m unittest discover -s tests
uv run prek run --all-files
```
