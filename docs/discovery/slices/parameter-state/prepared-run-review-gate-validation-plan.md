# Prepared Run Review Gate Validation Plan

## Status

Validation plan for an implementation candidate.

This is not an ADR, run-start contract, hardware-control contract, dependency
sync contract, parameter write-back contract, executor, managed-runner design,
GUI design, or shared gate schema.

## User Job

Given explicit prior review summaries for prepared-run context, parameter
state, scope alignment, workspace observation, and environment review, compose
one manual pre-run review state without starting a run, writing parameters,
syncing dependencies, probing runtimes, mutating workspaces, or controlling
hardware.

## Boundary To Validate

- gate authority is explicit prepared-run review composition;
- inputs are prior review summaries, not fresh observations or operations;
- required context, parameter state, scope alignment, workspace, and
  environment review areas are classified separately;
- missing required context takes precedence as `blocked_by_required_context`;
- otherwise unresolved area findings produce `manual_pre_run_review_needed`;
- all-clear inputs produce `ready_for_manual_review`;
- no run-start permission, hardware safety, parameter write-back, dependency
  resolution/sync, package installation, runtime probing, fresh storage or
  workspace observation, workspace mutation, code import/execution, managed
  runner, GUI behavior, or shared gate schema is accepted.

## Fixture

Use `tests/fixtures/prepared_run_review_gate/basic_gate/`.

The fixture is repository-safe synthetic data. It intentionally combines one
unavailable required context with scope, workspace, and environment findings,
while the parameter-state gate is ready. This is a consumer-side pressure case:
the fixture declares prior normalized findings and does not validate where the
required context came from on the producer side. The expected-output artifact
posture is `internal_validation_summary`; the candidate models a local manual
review surface, not a portable/export review artifact.

## Validation Steps

1. Validate fixture JSON and expected summary shape.
2. Validate review-gate policy and child-summary non-claims.
3. Validate prepared-run context and measurement identity continuity.
4. Validate parameter, scope, and environment child summaries reference the
   same prepared-run context.
5. Aggregate review items for required context, parameter, scope, workspace,
   and environment.
6. Apply precedence: required-context block first, then manual review needed,
   then ready for manual review.
7. Preserve all review findings without claiming run start, safety, repair, or
   execution readiness.

## Tests

- `tests/test_prepared_run_review_gate_fixture.py`
- `tests/test_prepared_run_review_gate_summary_candidate.py`

Run:

```bash
uv run python -m unittest tests.test_prepared_run_review_gate_fixture tests.test_prepared_run_review_gate_summary_candidate
uv run python -m unittest discover -s tests
uv run ruff check .
uv run ruff format --check .
```
