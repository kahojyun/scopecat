# Test Stages

Tests are organized by behavior stage. Promoted route-local prototype tests
live under `tests/prototypes/<route>/`. The old flat candidate-test surface has
been removed; the flat root is reserved for narrow repository-level tests such
as scan/data-shape discovery checks.

## Discovery Validation

Discovery tests are now exceptional and should answer a bounded evidence
question that is not yet owned by a live route. They must not import removed
candidate packages or make broad expected-output parity an accepted boundary.

Recommended names should describe the evidence question directly, for example
`test_scan_data_shape_generator.py`.

## Engineering Prototype

Engineering prototype tests prove route-local behavior. They should start from
route-native requests, commands, package/storage state, or explicit event-like
inputs, then assert the resulting operation, receipt, plan, review state, read
model, or non-mutation behavior.

Prototype tests should not primarily prove that a promoted API matches a
discovery candidate summary. If prior discovery evidence is still useful,
rename or wrap it as prior evidence and make route-native behavior the
acceptance surface.

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

When rewriting a test or adding coverage, choose the stage explicitly and
prefer the stage layout described in `docs/testing/fixture-policy.md`. Do not
add new flat candidate tests.
