# Calibration Parameter-State Storage Validation Result

## Status

Implementation candidate validated.

This is not an ADR, final storage architecture, general parameter-state
storage schema, read-view compatibility contract, compatibility-output
contract, hardware-control contract, rollback model, calibration executor, GUI
design, or shared domain model.

## Inputs

- [`calibration-parameter-state-intake-validation-result.md`](calibration-parameter-state-intake-validation-result.md)
- [`parameter-state-storage-writer-validation-result.md`](parameter-state-storage-writer-validation-result.md)
- [`../support/filesystem-mutation-helpers-validation-result.md`](../support/filesystem-mutation-helpers-validation-result.md)
- [`calibration-parameter-state-storage-validation-plan.md`](calibration-parameter-state-storage-validation-plan.md)
- `tests/fixtures/calibration_parameter_state_storage/basic_write/`
- `implementation_candidates/calibration_parameter_state_storage/`

## Validated Boundary

The fixture and implementation candidate validate a narrow storage boundary
for calibration-derived parameter-state intake:

- input authority is a validated calibration parameter-state intake summary;
- write authority is an approved calibration parameter-state storage request;
- destination paths are declared relative paths under a caller-provided storage
  root;
- existing state directory, manifest, or receipt targets are refused;
- one deterministic calibration-derived parameter-state manifest and one
  deterministic write receipt are written;
- digest and size facts are returned for both written files;
- calibration handoff, step, observation, base state, and intake review
  identities are preserved as provenance;
- no compatibility output, hardware write-back, rollback, calibration
  execution, GUI behavior, final storage architecture, storage read-view
  compatibility, or shared parameter schema is accepted.

The implementation candidate checks that the current summary can be built from
explicit fixture input while validating the nested calibration intake,
approved storage request, path topology, intake review and handoff identity
continuity, state identity continuity, no-overwrite targets, side-effect
claims, and optional expected digest facts. It uses the same low-level
filesystem mutation helpers as the adapter-derived storage writer, but it
preserves calibration provenance instead of coercing it into adapter/legacy
source fields.

## What The Summary Can Answer

The candidate summary can answer:

- which calibration-derived parameter state was written;
- which intake review and handoff produced it;
- which manifest and receipt paths were written;
- which bytes and sha256 digests were observed;
- what no-overwrite boundary was enforced;
- which calibration provenance was preserved;
- why storage does not imply compatibility output, hardware write-back,
  rollback, calibration execution, current instrument state, or final storage
  architecture.

The expected-output fixture is an `internal_validation_summary` repository
artifact. This slice does not validate portable/export review artifact
behavior.

## Remaining Questions

- Should adapter-derived and calibration-derived storage converge on a
  source-agnostic manifest schema?
- Should the existing parameter-state read view accept calibration-derived
  provenance, or should a separate source-agnostic read view be validated
  first?
- Should compatibility-output planning from a stored calibration-derived state
  remain generic parameter-state post-commit work?
- Should hardware apply recording wait until a separate hardware-control
  authority boundary exists?

## Not Earned

This validation does not earn:

- final storage architecture;
- general parameter-state storage schema;
- storage read-view compatibility;
- compatibility output;
- hardware write-back or current instrument state;
- rollback contract;
- calibration or measurement execution;
- measurement payload reading;
- fit execution;
- shared relation graph;
- GUI workflow;
- shared domain model extraction.

## Validation

- `uv run python -m unittest tests.test_calibration_parameter_state_storage_fixture tests.test_calibration_parameter_state_storage_summary_candidate`

## Slice Recommendation

Stop this slice at bounded local storage for calibration-derived
parameter-state summaries. The next useful slice is a source-agnostic
parameter-state storage/read-view projection if stored adapter-derived and
calibration-derived states need one common read surface.
