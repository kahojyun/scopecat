# Measurement Records Module

## Status

Current implementation owner for durable local Measurement Records.

This README is an API orientation for `scopecat.measurement_records`. It is not
a final storage architecture, public SDK contract, maintained product
capability, or shared domain model.

Use [`../../../docs/product/target-journeys.md`](../../../docs/product/target-journeys.md)
for canonical JNY/UC ownership,
[`../../../docs/product/target-capabilities.md`](../../../docs/product/target-capabilities.md)
for capability maturity, and
[`../../../docs/engineering/prototype-boundaries/measurement-records-storage.md`](../../../docs/engineering/prototype-boundaries/measurement-records-storage.md)
for accepted storage boundary details.

## Package-Root Entrypoints

Recording and import:

- `adopt_existing_run_from_request(...)`
- `import_measurement_record_from_source_by_id(...)`

Read-only access:

- `open_measurement_record(...)`

Declared context references:

- `record_measurement_record_references_from_request(...)`

These package-level APIs use typed request/value objects and hide canonical
record-local path construction from callers.

Route-local helpers such as legacy-run recording, converted-primary attach,
normalized-table summary, handoff preparation projection, path-explicit durable
import, and stored-primary reads remain submodule-owned implementation
surfaces. They may be used for route-local composition and tests, but they are
not package-root contracts.

## Boundary Split

The package-root JNY-007 facade supports adopt-first and import-ready recording
routes for already-produced measurements. `open_measurement_record(...)` opens
one canonical local record by `record_id` and returns user-shaped summaries.
The by-id import facade imports reviewed normalized primary data into canonical
`records/{record_id}` storage without caller-supplied record-local paths.

Measurement Records also owns declared reference receipts and the packageable
handoff projection consumed by `scopecat.handoff` selected-record export.

The module does not parse legacy files, scan sample workspaces, publish a final
storage schema, provide a catalog/index contract, own JNY-008 browse/plot UX,
or claim scientific validity.

## Artifact Orientation

Measurement Records storage is caller-rooted local storage. Ordinary local
storage, local receipts, read models, and local review surfaces are not
portable handoff artifacts unless an accepted boundary explicitly promotes
them.
