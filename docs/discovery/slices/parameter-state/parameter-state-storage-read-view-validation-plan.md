# Parameter State Storage Read View Validation Plan

## Status

Validation plan for an implementation candidate.

This is not an ADR, final storage architecture, catalog/index contract, legacy
parameter parser, schema migration contract, external file authority model,
hardware write-back contract, GUI design, or shared domain model.

## User Job

Given an explicit stored parameter-state manifest path and write-receipt path
under a caller-provided storage root, read the stored parameter state for local
review and consumption without scanning storage, mutating files, observing
legacy sources, migrating schemas, or writing hardware.

## Boundary To Validate

- read authority is an explicit parameter-state storage reference;
- the caller provides the storage root plus declared relative manifest and
  receipt paths;
- only the declared manifest and receipt files are read;
- sha256 and byte-size facts are compared against the explicit read request;
- receipt-to-manifest continuity and requested state identity are checked;
- trusted entries, provenance, excluded preview entries, source review facts,
  and receipt facts are projected for review;
- unavailable and mismatch states are returned as review findings;
- no catalog discovery, storage mutation, legacy source observation, schema
  migration, external file authority, hardware write-back, GUI behavior, shared
  parameter schema, or final storage architecture is accepted.

## Fixture

Use `tests/fixtures/parameter_state_storage_read_view/basic_read/`.

The fixture is repository-safe synthetic data. It reuses the deterministic
manifest and write receipt produced by the storage-writer slice for the same
reviewed adapter import scenario. The validation summary posture is
`internal_validation_summary`.

## Validation Steps

1. Validate fixture JSON and expected summary shape.
2. Read the explicit manifest and receipt under the fixture storage root.
3. Compare observed sha256 and size facts with request facts.
4. Check receipt manifest path, digest, size, and state identity continuity.
5. Project trusted entries, provenance, excluded preview entries, source review
   facts, and receipt facts.
6. Exercise mismatch and unavailable states as review findings.
7. Reject positive claims or unsafe paths that would cross the read-view
   boundary.

## Tests

- `tests/test_parameter_state_storage_read_view_fixture.py`
- `tests/test_parameter_state_storage_read_view_summary_candidate.py`

Run:

```bash
uv run python -m unittest tests.test_parameter_state_storage_read_view_fixture tests.test_parameter_state_storage_read_view_summary_candidate
uv run python -m unittest discover -s tests
uv run ruff check .
uv run ruff format --check .
```
