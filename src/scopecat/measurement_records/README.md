# Measurement Records Module

## Status

Current engineering-prototype implementation owner for durable local
Measurement Records.

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
For accepted prototype boundaries, use
[`../../../docs/engineering/prototype-boundaries/measurement-records-creation-lifecycle.md`](../../../docs/engineering/prototype-boundaries/measurement-records-creation-lifecycle.md)
and
[`../../../docs/engineering/prototype-boundaries/measurement-records-legacy-run-storage.md`](../../../docs/engineering/prototype-boundaries/measurement-records-legacy-run-storage.md).
Historical slice-by-slice promotion notes live in [`HISTORY.md`](HISTORY.md).

## Current Surfaces

Durable record creation and primary-data pipeline:

- `create_measurement_record(...)`
- `write_created_record_primary_data(...)`
- `summarize_normalized_primary_table(...)`
- `read_created_record_primary_table(...)`
- `finalize_measurement_record(...)`
- `project_measurement_record_read_model(...)`
- `catalog_measurement_record_read_models(...)`
- `refresh_measurement_record_read_model(...)`
- `import_measurement_record(...)`

Legacy and brownfield storage review:

- `record_legacy_measurement_run(...)`
- `attach_converted_primary_data_to_legacy_record(...)`
- `record_measurement_record_references(...)`
- `record_legacy_measurement(...)`
- `list_measurement_record_storage(...)`

In-progress and existing-record local review:

- `append_in_progress_measurement_record(...)`
- `inspect_running_measurement_record(...)`
- `append_existing_measurement_record(...)`
- `review_measurement_records(...)`
- `save_measurement_record_operator_review_receipt(...)`
- `summarize_measurement_record_operator_review_receipt(...)`
- `build_measurement_record_review_html(...)`
- `write_measurement_record_review_artifact(...)`

Supporting projection helpers:

- `summarize_running_measurement_inspection(...)`
- `legacy_measurement_slug(...)`

Dictionary/request adapter functions with `_from_request` suffix mirror the
main mutation and review entrypoints where raw request parsing belongs at the
module boundary. Treat lower-level helpers and private modules as route-local
implementation details, not shared APIs.

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
are not portable handoff artifacts unless a slice explicitly promotes them.

## CLI Smoke Surfaces

The module exposes narrow local smoke commands:

```sh
python -m scopecat.measurement_records running-inspection-summary ...
python -m scopecat.measurement_records operator-review ...
python -m scopecat.measurement_records record-legacy-run ...
python -m scopecat.measurement_records storage-inventory ...
python -m scopecat.measurement_records operator-review-receipt-summary ...
```

These commands are local review and smoke surfaces. They do not discover
records broadly, run import/refresh/finalization automatically, repair storage,
persist GUI state, or become public product CLI contracts.

## Tests And Fixtures

Module behavior is covered by prototype tests under
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
prototype-boundary notes linked above.
