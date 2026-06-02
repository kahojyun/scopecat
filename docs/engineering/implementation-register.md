# Implementation Register

## Status

Current implementation ownership register.

## Purpose

Track live implementation owners: modules, entrypoints, tests, fixtures,
artifact boundaries, and scope boundaries. This is an engineering inventory,
not a product capability map or adoption model.

Use this document with:

- [`../product/capability-map.md`](../product/capability-map.md) for product
  capability maturity;
- [`workflow-validation-map.md`](workflow-validation-map.md) for workflow seams
  and validation questions;
- [`prototype-boundaries/README.md`](prototype-boundaries/README.md) for
  route-local engineering prototype boundaries.

## Implementation Owners

| Implementation Owner | Maturity | Product Capability | Entrypoint Or Surface | Storage Or Artifact Boundary | Tests And Fixtures | Boundary Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `scopecat.measurement_records` durable creation and primary-data pipeline | Engineering prototype | Measurement Records | `create_measurement_record(...)`, writer integration, read view, finalization, read-model projection/catalog/refresh, durable import. | Caller-provided storage root; record-local manifest, receipts, primary CSV, and derived `record-read-model.json`. | Measurement Records unit and fixture tests under `tests/` and `tests/fixtures/measurement_*`; module README owns exact API list. | [`src/scopecat/measurement_records/README.md`](../../src/scopecat/measurement_records/README.md), [`prototype-boundaries/measurement-records-creation-lifecycle.md`](prototype-boundaries/measurement-records-creation-lifecycle.md) |
| `scopecat.measurement_records` legacy run storage, converted-primary attach, references, inventory, and local review | Engineering prototype | Measurement Records | `record_legacy_measurement_run(...)`, `attach_converted_primary_data_to_legacy_record(...)`, `record_measurement_record_references(...)`, `record_legacy_measurement(...)`, storage inventory and local review surfaces. | Same Measurement Records storage root; record-local legacy receipt, optional primary-data receipts/read-model, recorded-reference receipts, local review artifact. | Legacy storage and scenario fixtures under `tests/fixtures/*legacy*` plus `scripts/scenarios/legacy_run_storage_gui.py`. | [`src/scopecat/measurement_records/README.md`](../../src/scopecat/measurement_records/README.md), [`prototype-boundaries/measurement-records-legacy-run-storage.md`](prototype-boundaries/measurement-records-legacy-run-storage.md) |
| `scopecat.handoff` package writer, read-only package use, local inspection, receiving gate, import plan, durable import adapter | Engineering prototype | Handoff Packages | `write_package(...)`, `run_package_workflow(...)`, `open_package(...)`, `observe_package_integrity(...)`, `run_receiving_gate(...)`, `run_import_plan(...)`, `run_handoff_durable_import(...)`. | Directory-shaped package subset; package manifest as portable package index; local inspection HTML and function returns are local review artifacts unless separately promoted. Durable import delegates storage mutation to Measurement Records. | Handoff package fixtures under `tests/fixtures/handoff_*` and `tests/fixtures/prototypes/handoff/`; module tests own exact behavior. | [`src/scopecat/handoff/README.md`](../../src/scopecat/handoff/README.md), [`prototype-boundaries/handoff.md`](prototype-boundaries/handoff.md), [`prototype-boundaries/handoff-durable-import-storage.md`](prototype-boundaries/handoff-durable-import-storage.md) |
| `scopecat.environment_operation` approved `uv` sync execution/review/probe | Engineering prototype | Environment Operation | `UvSyncIntent.from_summary(...)`, `execute_uv_sync(...)`, `UvSyncResult.from_execution(...)`, `review_uv_sync_operation(...)`, runtime probe APIs, `run_uv_sync_operation(...)`. | Local review summaries and typed route-local result/review objects; no portable/export projection of local paths or output snippets. | Environment-operation tests and fixtures under `tests/fixtures/*environment*` and `tests/fixtures/prototypes/environment_operation/`. | [`src/scopecat/environment_operation/README.md`](../../src/scopecat/environment_operation/README.md), [`prototype-boundaries/environment-operation.md`](prototype-boundaries/environment-operation.md) |
| `scopecat.parameter_state` review, storage, read view, selection, and route-local pre-run consumption | Engineering prototype | Parameter State Review | Adapter import preview/review APIs, storage writer/read view, source-agnostic read projection, selection context, prepared-run consumption/gate/scope/review chain APIs. | Caller-rooted explicit parameter-state storage paths; manifest/receipt read views; local review summaries. | Parameter-state fixtures under `tests/fixtures/*parameter*` and matching unit tests. | [`src/scopecat/parameter_state/README.md`](../../src/scopecat/parameter_state/README.md), [`prototype-boundaries/parameter-state.md`](prototype-boundaries/parameter-state.md) |

## Update Rule

Update this register when live code:

- adds or retires an implementation owner;
- changes an owner entrypoint, artifact authority, tests, fixtures, or boundary
  note;
- promotes a workflow gap into live route-local code;
- supersedes a historical candidate path.

Do not copy product capability strategy here. Link to
[`../product/capability-map.md`](../product/capability-map.md) instead.
