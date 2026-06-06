# Measurement Records Module

## Status

Current implementation owner for durable local Measurement Records.

This module owns the live route-local APIs for importing, adopting, and linking
local measurement records. It is not a final storage architecture,
public SDK contract, maintained product capability, or shared domain model.
It supports the target journeys for recording/adopting measurements and
selected-record handoff, but it does not own those full product journeys.

For workflow and implementation ownership, start from
[`../../../docs/engineering/workflow-validation-map.md`](../../../docs/engineering/workflow-validation-map.md)
and
[`../../../docs/engineering/implementation-register.md`](../../../docs/engineering/implementation-register.md).
For product capability maturity, use
[`../../../docs/product/target-capabilities.md`](../../../docs/product/target-capabilities.md).
For accepted engineering boundaries, use
[`../../../docs/engineering/prototype-boundaries/measurement-records-creation-lifecycle.md`](../../../docs/engineering/prototype-boundaries/measurement-records-creation-lifecycle.md)
and
[`../../../docs/engineering/prototype-boundaries/measurement-records-legacy-run-storage.md`](../../../docs/engineering/prototype-boundaries/measurement-records-legacy-run-storage.md).

## Package-Level Surfaces

The package root exposes current caller-facing Measurement Records
capabilities:

- `adopt_existing_run_from_request(...)` for JNY-007 basic UX: adopt an
  already-produced measurement through an adopt-first or import-ready route
  while hiding canonical record-local path construction;
- `open_measurement_record(...)` for opening one canonical local record by
  `record_id` and reviewing user-shaped record, source-locator, openable
  primary-data, and reference-set summaries;
- `import_measurement_record_from_request(...)` for importing reviewed
  normalized primary data into durable local storage;
- `record_measurement_record_references_from_request(...)` for declared
  context links attached to a Measurement Record.

These package-level APIs use typed request/value objects. Slice-level
operations such as legacy-run recording, converted-primary attach,
normalized-table summary, and stored-primary reads remain
available only from their owning internal modules for route-local composition,
tests, and future cleanup.
Do not treat those submodule entrypoints as package-level contracts.
The adoption facade and open-by-id view are workflow UX helpers for the current
JNY-007 engineering prototype; they do not publish a final storage schema,
catalog/index contract, legacy parser, or JNY-008 browsing surface.

## Artifact Boundaries

Measurement Records storage is caller-rooted local storage. Current accepted
record-local artifacts include:

- `record-manifest.json` as the immutable creation shell and origin identity;
- record-local receipts for writer, finalization, import, legacy-run recording,
  and references;
- primary CSV bytes written through approved writer/import paths;
- derived `record-read-model.json` as a replaceable local convenience
  summary, not canonical storage authority.

Runtime redaction is required only at declared or effective portable/export
boundaries. Ordinary local storage, local receipts, and local review surfaces
are not portable handoff artifacts unless an accepted boundary explicitly
promotes them.

## Tests And Fixtures

Package-level behavior and route-local submodule behavior are covered by tests under
[`../../../tests/prototypes/measurement_records/`](../../../tests/prototypes/measurement_records/)
and selected repository-safe fixture families under
[`../../../tests/fixtures/`](../../../tests/fixtures/). Run the repository
checks with:

```sh
uv run python -m unittest discover -s tests
uv run ruff check .
uv run ruff format --check .
```

## Boundary

This README owns live API orientation. Detailed scope limits live in the
engineering boundary notes linked above.
