# Vertical Slice Register

## Status

Engineering slice register, not an ADR, roadmap, or module API reference.

## Purpose

This register records accepted implementation slices and their current owners.
It complements [`workflow-validation-map.md`](workflow-validation-map.md):

- the workflow map answers what user workflow has been validated;
- this register answers which implementation slice owns the code, tests,
  fixtures, artifacts, and non-goals.

Use this document before adding live code or before treating a discovery
candidate as accepted implementation.

## Slice Register

| Slice | Phase | Workflow Covered | Entrypoint Or Surface | Storage Or Artifact Boundary | Tests And Fixtures | Owner | Accepted Non-Goals |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Measurement Records durable creation and primary-data pipeline | Engineering prototype | Normalized primary data becomes a durable Measurement Record. | `create_measurement_record(...)`, writer integration, read view, finalization, read-model projection/catalog/refresh, durable import. | Caller-provided storage root; record-local manifest, receipts, primary CSV, and derived `record-read-model.json`. | Measurement Records unit and fixture tests under `tests/` and `tests/fixtures/measurement_*`; module README owns exact API list. | [`src/scopecat/measurement_records/README.md`](../../src/scopecat/measurement_records/README.md), [`docs/architecture/boundaries/measurement-records-creation-lifecycle.md`](../architecture/boundaries/measurement-records-creation-lifecycle.md) | Final storage schema, public SDK, manifest replacement, shared domain model, broad import/update behavior. |
| Legacy run storage, converted-primary attach, references, inventory, and local review | Engineering prototype | Legacy external run becomes visible in local storage. | `record_legacy_measurement_run(...)`, `attach_converted_primary_data_to_legacy_record(...)`, `record_measurement_record_references(...)`, `record_legacy_measurement(...)`, storage inventory and local review surfaces. | Same Measurement Records storage root; record-local legacy receipt, optional primary-data receipts/read-model, recorded-reference receipts, local review artifact. | Legacy storage and scenario fixtures under `tests/fixtures/*legacy*` plus `scripts/scenarios/legacy_run_storage_gui.py`. | [`src/scopecat/measurement_records/README.md`](../../src/scopecat/measurement_records/README.md), [`docs/architecture/boundaries/measurement-records-legacy-run-storage.md`](../architecture/boundaries/measurement-records-legacy-run-storage.md) | Legacy file observation/parsing, source payload import, legacy execution, scientific validity, GUI state persistence, reference repair. |
| Handoff package writer, read-only package use, local inspection, receiving gate, import plan, durable import adapter | Engineering prototype | Source-root data becomes a local handoff package; handoff package is received and imported into local storage. | `write_package(...)`, `run_package_workflow(...)`, `open_package(...)`, `observe_package_integrity(...)`, `run_receiving_gate(...)`, `run_import_plan(...)`, `run_handoff_durable_import(...)`. | Directory-shaped package subset; package manifest as portable package index; local inspection HTML and function returns are local review artifacts unless separately promoted. Durable import delegates storage mutation to Measurement Records. | Handoff package fixtures under `tests/fixtures/handoff_*` and `tests/fixtures/prototypes/handoff/`; module tests own exact behavior. | [`src/scopecat/handoff/README.md`](../../src/scopecat/handoff/README.md), [`docs/architecture/boundaries/handoff.md`](../architecture/boundaries/handoff.md), [`docs/architecture/boundaries/handoff-durable-import-storage.md`](../architecture/boundaries/handoff-durable-import-storage.md) | Archive format, signatures/authenticity, batch import, linked-context payload import, final storage schema, broad receiving workflow. |
| Environment operation approved `uv` sync execution/review/probe | Engineering prototype | Approved `uv sync` intent becomes local environment-operation review evidence. | `UvSyncIntent.from_summary(...)`, `execute_uv_sync(...)`, `UvSyncResult.from_execution(...)`, `review_uv_sync_operation(...)`, runtime probe APIs, `run_uv_sync_operation(...)`. | Local review summaries and typed route-local result/review objects; no portable/export projection of local paths or output snippets. | Environment-operation tests and fixtures under `tests/fixtures/*environment*` and `tests/fixtures/prototypes/environment_operation/`. | [`src/scopecat/environment_operation/README.md`](../../src/scopecat/environment_operation/README.md), [`docs/architecture/boundaries/environment-operation.md`](../architecture/boundaries/environment-operation.md) | Runtime readiness, package-state verification, selected-code execution, hardware readiness, multi-manager abstraction, general process executor. |
| Parameter-state review, storage, read view, selection, and route-local pre-run consumption | Engineering prototype | Parameter state is reviewed, stored, read, and consumed for manual pre-run review. | Adapter import preview/review APIs, storage writer/read view, source-agnostic read projection, selection context, prepared-run consumption/gate/scope/review chain APIs. | Caller-rooted explicit parameter-state storage paths; manifest/receipt read views; local review summaries. | Parameter-state fixtures under `tests/fixtures/*parameter*` and matching unit tests. | [`src/scopecat/parameter_state/README.md`](../../src/scopecat/parameter_state/README.md), [`docs/architecture/boundaries/parameter-state.md`](../architecture/boundaries/parameter-state.md) | Hardware apply, compatibility-file writing, live source-file write-back, catalog discovery, automatic run start, shared parameter/run-context schema. |

## Composition Gaps

| Gap | Existing Accepted Ends | Missing Slice | Why It Matters |
| --- | --- | --- | --- |
| Legacy measurement portable handoff | Legacy run can become Measurement Records storage; handoff package can be received, previewed, gated, and imported into another storage root. | Selected stored Measurement Record to single-measurement handoff package export. | This is the missing seam for a brownfield adoption workflow where a user records a legacy run, selects one measurement, exports it, previews it on another computer, and imports it into storage while preserving identity continuity. |

## Update Rule

Update this register when live code:

- adds or retires an accepted implementation slice;
- changes a slice's entrypoint, artifact authority, tests, or non-goals;
- promotes a composition gap into an engineering prototype or production
  vertical slice;
- supersedes a historical candidate path.

Do not copy validation-result tables here. Link to the owner and summarize only
the accepted implementation boundary.
