# Source-Agnostic Parameter-State Read View Validation Result

## Status

Implementation candidate validated.

This is not an ADR, final storage architecture, catalog/index contract,
storage mutation contract, compatibility-output contract, hardware-control
contract, schema migration, GUI design, universal provenance schema, or shared
domain model.

## Inputs

- [`parameter-state-storage-read-view-validation-result.md`](parameter-state-storage-read-view-validation-result.md)
- [`calibration-parameter-state-storage-validation-result.md`](calibration-parameter-state-storage-validation-result.md)
- [`parameter-state-storage-writer-validation-result.md`](parameter-state-storage-writer-validation-result.md)
- [`source-agnostic-parameter-state-read-view-validation-plan.md`](source-agnostic-parameter-state-read-view-validation-plan.md)
- `tests/fixtures/source_agnostic_parameter_state_read_view/basic_read/`
- `implementation_candidates/source_agnostic_parameter_state_read_view/`

## Validated Boundary

The fixture and implementation candidate validate a narrow source-agnostic
parameter-state read-view boundary:

- input authority is an explicit list of stored parameter-state manifest and
  receipt references;
- adapter-derived and calibration-derived manifest/receipt schemas are
  accepted as source variants;
- only declared manifest and receipt files are read under a caller-provided
  storage root;
- observed sha256 and byte-size facts are compared with explicit request facts;
- receipt manifest path, digest, size, storage mutation, state id, and
  requested state id continuity are checked;
- common state facts are projected across source families: state identity,
  kind, label, lineage, readiness, trust status, trusted entry paths, and
  trusted entries;
- adapter provenance and calibration provenance are preserved as typed
  provenance payloads rather than normalized into one universal schema;
- unavailable files and digest, size, source-kind, receipt, or state identity
  mismatches surface as review findings;
- no catalog discovery, storage mutation, compatibility output, hardware
  write-back, schema migration, GUI behavior, final storage architecture, or
  universal provenance schema is accepted.

The implementation candidate checks that the current summary can be built from
explicit fixture input while validating policy claims, request path and digest
facts, adapter and calibration manifest shapes, typed provenance references,
receipt shape, receipt-to-manifest continuity, and symlink guardrails. The
builder returns only the candidate summary, not fixture status,
reference-semantics, or decisions-not-earned text.

## What The Summary Can Answer

The candidate summary can answer:

- which explicit stored parameter states were read;
- whether each adapter-derived or calibration-derived state is ready,
  unavailable, or observed with mismatches;
- which manifest and receipt files were observed;
- whether observed digest and size facts match request and receipt facts;
- which common parameter-state facts and trusted entries are visible;
- which typed provenance payload is attached to each state;
- why reading stored parameter state does not imply catalog discovery, storage
  mutation, compatibility output, hardware write-back, schema migration,
  current instrument state, or a universal provenance schema.

The expected-output fixture is an `internal_validation_summary` repository
artifact. This slice does not validate portable/export review artifact
behavior.

## Remaining Questions

- Should future storage writers converge on one source-agnostic manifest
  schema, or should typed manifest variants remain acceptable behind this read
  surface?
- Should a storage catalog/index discover explicit read references for this
  view?
- Should generated compatibility artifacts remain outside this read view unless
  supplied as debug/attachment evidence?
- Should prepared-run parameter-state consumption switch from the adapter-only
  read view to this source-agnostic read view?

## Not Earned

This validation does not earn:

- final storage architecture;
- catalog or index discovery;
- storage mutation, repair, or migration;
- compatibility output;
- hardware write-back or current instrument state;
- schema migration;
- universal provenance schema;
- GUI workflow;
- shared domain model extraction.

## Validation

- `uv run python -m unittest tests.test_source_agnostic_parameter_state_read_view_fixture tests.test_source_agnostic_parameter_state_read_view_summary_candidate`

## Slice Recommendation

Stop this slice at explicit source-agnostic read projection. The next useful
slice is prepared-run consumption of this read view if calibration-derived
parameter states need to participate in run-preparation review.
