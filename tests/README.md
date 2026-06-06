# Test Stages

Tests are organized by behavior stage. Prototype tests live under
`tests/prototypes/<owner>/`. Integration tests live under
`tests/integration/<workflow>/`. Discovery tests live under
`tests/discovery/<topic>/`. The flat root is reserved only for narrow
repository-level checks that do not fit a stage-specific owner.

## Discovery Validation

Discovery tests are now exceptional and should answer a bounded evidence
question that is not yet owned by a live implementation owner. They must not
import candidate packages or make broad expected-output parity an accepted
boundary.

Current layout:

```text
tests/discovery/scan_data_shapes/
tests/fixtures/discovery/scan_data_shapes/
```

Recommended names should describe the evidence question directly, for example
`test_scan_data_shape_generator.py`.

## Engineering Prototype

Engineering prototype tests prove implementation-owner behavior. They should
start from owner-native requests, commands, package/storage state, or explicit
event-like inputs, then assert the resulting operation, receipt, plan, review
state, read model, or non-mutation behavior.

Prototype tests should not primarily prove that a promoted API matches a
discovery candidate summary. If prior discovery evidence is still useful,
rename or wrap it as prior evidence and make owner-native behavior the
acceptance surface.

Recommended names:

- `test_<owner>_<operation>.py`
- `test_<owner>_<workflow_step>.py`

Current layout:

```text
tests/prototypes/handoff/
tests/prototypes/measurement_records/
```

Good assertion targets:

- approval gates and rejected requests;
- no-overwrite and rollback behavior;
- files written or deliberately not written;
- receipt and read-model continuity;
- review findings and next required decision;
- explicit operation facts attached to a real workflow step.

## Integration And Workflow

Integration/workflow tests prove that a user-visible step works across owner
boundaries or real entrypoints. They should start from realistic local
storage/package/CLI/API state and end with a next usable user result.

Recommended names:

- `test_<journey>_<workflow>.py`
- `test_<owner>_<workflow>.py`

Current layout:

```text
tests/integration/handoff/
```

These tests should not assert discovery expected-output parity. They may reuse
prototype fixtures as input state or discovery fixtures as input evidence, but
the acceptance target is the workflow result.

## Migration Rule

When rewriting a test or adding coverage, choose the stage explicitly and
prefer the stage layout described in `docs/testing/fixture-policy.md`. Do not
add new flat candidate tests.
