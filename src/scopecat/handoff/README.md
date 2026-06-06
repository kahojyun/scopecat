# Handoff Module

## Status

Current implementation owner for Scopecat-authored handoff package use and
durable Measurement Records handoff import adaptation.

This README is an API orientation for `scopecat.handoff`. Boundary details live
in:

- [`../../../docs/engineering/prototype-boundaries/handoff.md`](../../../docs/engineering/prototype-boundaries/handoff.md)
- [`../../../docs/engineering/prototype-boundaries/handoff-durable-import-storage.md`](../../../docs/engineering/prototype-boundaries/handoff-durable-import-storage.md)

Use [`../../../docs/product/target-journeys.md`](../../../docs/product/target-journeys.md)
for canonical JNY/UC ownership and
[`../../../docs/engineering/implementation-register.md`](../../../docs/engineering/implementation-register.md)
for implementation ownership.

## Package-Root Entrypoints

Selected stored-record export:

- `export_selected_measurement_record_from_request(request, storage_root=..., package_root=...)`
- `export_selected_measurement_record_batch_from_request(request, storage_root=..., package_root=...)`

Package open and receiving review:

- `open_package(package_dir)`
- `observe_package_integrity(package_dir)`
- `run_receiving_gate_from_request(request, package_dir=...)`
- `build_import_plan(request, receiving_gate=...)`

Archive transport:

- `create_handoff_archive_package_from_request(request)`
- `materialize_handoff_archive_package_from_request(request)`

Durable import adapter:

- `run_handoff_durable_import_from_plan(request, import_plan=..., storage_root=...)`

Package-root request/value classes are the caller-facing operation inputs and
outputs. Route projection objects, run/result objects, direct writer helpers,
and durable-request builder helpers may remain importable from owning
submodules for route-local composition, but they are not package-root
contracts.

`HandoffError` and `HandoffContractError` are the package-root error types.
Modules with leading underscores are route-private implementation modules.

## Boundary Split

`scopecat.handoff` owns package writing/opening, selected-record package export,
receiving gates, non-mutating import plans, archive transport helpers, and the
handoff-to-Measurement-Records durable import adapter.

It does not own Measurement Record creation outside delegated import, record
storage schema, run recording, running updates, post-run result review,
external authenticity, trusted-source policy, or scientific validity.

Selected stored-record export consumes a Measurement Records-owned packageable
projection by `record_id`. Handoff does not parse Measurement Record storage
artifacts directly.

Durable import adapts exactly one ready import-plan measurement into
Measurement Records by-id import. Storage mutation, canonical record paths,
primary-data validation, read-model writing, rollback classification, and
new-record no-overwrite behavior remain delegated to
`scopecat.measurement_records`.

## Artifact Orientation

The handoff package directory and `package-manifest.json` are portable handoff
artifacts. Local writer receipts, function return values, receiving-gate
results, import-plan objects, selected-export receipts, and durable-import
adapter receipts are local review surfaces unless a later accepted boundary
promotes one.

Package-format, trust, archive, batch, linked-context, and existing-record
deferral decisions live in the ADRs linked from the boundary notes.
