# Test Stages

Tests are organized by behavior stage. Promoted route-local prototype tests
live under `tests/prototypes/<route>/`; older discovery and candidate tests
still use the flat historical layout under `tests/`.

## Discovery Validation

Discovery tests prove candidate concepts, boundaries, finding vocabularies, and
non-claims. They may:

- import from `implementation_candidates`;
- load `candidate_summary` from expected-output fixtures;
- assert full JSON parity against expected discovery outputs;
- use synthetic fields that make boundary behavior explicit.

Recommended names:

- `test_<slice>_summary_candidate.py`
- `test_<slice>_fixture.py`

## Engineering Prototype

Engineering prototype tests prove route-local behavior. They should start from
route-native requests, commands, package/storage state, or explicit event-like
inputs, then assert the resulting operation, receipt, plan, review state, read
model, or non-mutation behavior.

Prototype tests should not primarily prove that a promoted API matches a
discovery candidate summary. If compatibility with a discovery shape matters,
keep that as a small adapter test and make behavior tests the acceptance
surface.

Recommended names:

- `test_<route>_<operation>_prototype.py`
- `test_<route>_<workflow_step>_prototype.py`

Current layout:

```text
tests/prototypes/environment_operation/
tests/prototypes/handoff/
tests/prototypes/measurement_records/
tests/prototypes/parameter_state/
```

Good assertion targets:

- approval gates and rejected requests;
- no-overwrite and rollback behavior;
- files written or deliberately not written;
- receipt and read-model continuity;
- review findings and next required decision;
- explicit non-claims attached to a real workflow step.

## Integration And Workflow

Integration/workflow tests prove that a user-visible step works across route
boundaries or real entrypoints. They should start from realistic local
storage/package/CLI/API state and end with a next usable user result.

Recommended names:

- `test_<workflow>_workflow.py`
- `test_<route>_integration.py`

These tests should not assert discovery expected-output parity. They may reuse
discovery fixtures as input evidence, but the acceptance target is the workflow
result.

## Migration Rule

Existing tests do not need to move just to satisfy naming. When rewriting a
test or adding coverage, choose the stage explicitly and prefer the stage
layout described in `tests/fixtures/README.md`.
