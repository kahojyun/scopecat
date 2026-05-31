# Prepared Run Scope Alignment Validation Plan

## Status

Validation plan for an implementation candidate.

This is not an ADR, shared parameter/setup/measurement schema, automatic
parameter invalidation policy, run-start contract, hardware-control contract,
executor, GUI design, or final storage architecture.

## User Job

Given prepared-run parameter-state consumption facts and setup-binding facts,
compare selected parameter lineage target scope, manual-run logical targets,
selected setup binding, and setup sample context for review without writing
parameters, controlling hardware, reading storage, mutating setup, or starting
a run.

## Boundary To Validate

- alignment authority is declared prepared-run scope review;
- parameter context comes from a prepared-run parameter-state consumption
  summary;
- setup binding comes from a declared setup-binding summary;
- measurement intent comes from the prepared-run manual target;
- sample mismatch, lineage-sample mismatch, missing setup binding targets,
  absent lineage target coverage, and partial lineage target coverage become
  review findings;
- partial parameter-lineage target coverage is review-worthy but does not
  automatically invalidate parameters or block a run;
- no parameter write-back, hardware control, automatic run start, fresh storage
  read, catalog discovery, setup mutation, environment sync, code execution,
  GUI behavior, or shared scope schema is accepted.

## Fixture

Use `tests/fixtures/prepared_run_scope_alignment/basic_alignment/`.

The fixture is repository-safe synthetic data. It intentionally models a
useful pressure case: setup binding covers both `qA` and `cAB`, while the
selected parameter lineage is scoped to `qA`, so the candidate emits a partial
target-coverage finding without claiming automatic invalidation. The validation
summary posture is `internal_validation_summary`.

## Validation Steps

1. Validate fixture JSON and expected summary shape.
2. Validate alignment policy and request continuity.
3. Validate consumed summary side-effect non-claims.
4. Validate setup-binding summary references used by the alignment request.
5. Compare expected sample with setup binding and parameter lineage scope.
6. Compare manual-run logical targets with selected setup-binding logical
   entities.
7. Compare manual-run logical targets with parameter lineage target scope.
8. Surface findings without hardware, write-back, execution, or automatic
   invalidation claims.

## Tests

- `tests/test_prepared_run_scope_alignment_fixture.py`
- `tests/test_prepared_run_scope_alignment_summary_candidate.py`

Run:

```bash
uv run python -m unittest tests.test_prepared_run_scope_alignment_fixture tests.test_prepared_run_scope_alignment_summary_candidate
uv run python -m unittest discover -s tests
uv run prek run --all-files
```
