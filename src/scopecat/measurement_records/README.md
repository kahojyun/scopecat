# Measurement Records Module

## Status

Current implementation owner for durable local Measurement Records.

This module owns the live route-local APIs for creating, importing, reviewing,
and reading local measurement records. It is not a final storage architecture,
public SDK contract, maintained product capability, or shared domain model.
It supports the target journeys for recording/adopting measurements,
post-run results review, running inspection, and selected-record handoff, but it
does not own those full product journeys.

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
Historical slice-by-slice promotion notes live in [`HISTORY.md`](HISTORY.md).

## Package-Level Surfaces

The package root exposes current caller-facing Measurement Records
capabilities:

- `import_measurement_record_from_request(...)` for importing reviewed
  normalized primary data into durable local storage;
- `record_legacy_measurement(...)` and
  `record_legacy_measurement_from_request(...)` for adopting one legacy or
  externally executed measurement behind user-facing facts;
- `record_measurement_record_references_from_request(...)` and
  `list_measurement_record_references(...)` for declared context links attached
  to a Measurement Record;
- `review_measurement_records_from_request(...)` for local Measurement Records
  review.

These package-level APIs use typed request/value objects. Slice-level
operations such as creation, writer integration, finalization, read-model
projection/refresh/catalog, normalized-table summary, storage inventory,
in-progress update, existing-record update, operator-review receipt writing,
and static review artifact writing remain available only from their owning
submodules for route-local composition, tests, and future cleanup. Do not treat
those submodule entrypoints as package-level contracts.

## Artifact Boundaries

Measurement Records storage is caller-rooted local storage. Current accepted
record-local artifacts include:

- `record-manifest.json` as the immutable creation shell and origin identity;
- record-local receipts for creation, writer integration, finalization, import,
  legacy-run recording, references, and updates;
- primary CSV bytes written through approved writer/import paths;
- derived `record-read-model.json` as a replaceable local convenience
  projection, not canonical storage authority;
- local review HTML and operator-review continuation receipts written outside
  durable record storage authority.

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
