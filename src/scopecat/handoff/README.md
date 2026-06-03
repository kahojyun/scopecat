# Handoff Prototype Module

## Status

Current engineering-prototype implementation owner for Scopecat-authored
handoff package use and durable Measurement Records handoff import adaptation.

This module is route-local prototype code. It exposes production-shaped Python
entrypoints over validated handoff discovery evidence. Boundary details live in
the prototype-boundary notes linked below.

For workflow and implementation ownership, start from
[`../../../docs/engineering/workflow-validation-map.md`](../../../docs/engineering/workflow-validation-map.md)
and
[`../../../docs/engineering/implementation-register.md`](../../../docs/engineering/implementation-register.md).
For accepted boundaries, start from
[`../../../docs/engineering/prototype-boundaries/handoff.md`](../../../docs/engineering/prototype-boundaries/handoff.md)
and
[`../../../docs/engineering/prototype-boundaries/handoff-durable-import-storage.md`](../../../docs/engineering/prototype-boundaries/handoff-durable-import-storage.md).

## Current Surfaces

Package writer and local package workflow:

- `write_package(source, source_root=..., package_root=...)`
- `run_package_workflow(source, source_root=..., package_root=...)`
- `export_selected_measurement_record_from_request(request, storage_root=..., package_root=...)`
- `export_selected_measurement_record(source, storage_root=..., package_root=...)`

Read-only package use and local review:

- `open_package(package_dir)`
- `summarize_package_context_references(package)`
- `build_inspection_html(...)`
- `write_inspection_artifact(...)`

Receiving-side read-only planning:

- `observe_package_integrity(package_dir)`
- `run_receiving_gate(source, package_dir=...)`
- `run_import_plan(source, package_dir=...)`

Durable Measurement Records import adaptation:

- `run_handoff_durable_import(source, package_dir=..., storage_root=...)`
- `run_handoff_durable_import_from_plan(request, import_plan=..., storage_root=...)`
- `build_durable_import_request_from_handoff_plan(request, import_plan=...)`
- `summarize_handoff_durable_import_receipt(receipt)`
- `review_handoff_durable_import_retry(previous_summary, fresh_import_plan=...)`

The top-level module also exports route projection objects such as
`HandoffPackage`, `HandoffMeasurement`, `HandoffTable`, `HandoffPlotSeries`,
receiving/import run objects, and durable-import receipt/retry summaries.
Modules with leading underscores are route-private implementation modules.

## Boundary Split

Raw manifest dictionaries are validated at the package boundary. After that,
manifest preview classification, opener internals, review findings, and
package projections consume typed route-local manifest fragments. Raw workflow
dictionaries are accepted only at public `run_*` edge adapters; internal
composition should pass typed route-local request and run objects.

`run_import_plan(...)` is a non-mutating plan. It names package members that
could be considered for later acceptance, but accepts no destination path,
performs no conflict detection, writes no storage records, and does not decide
final storage schema or rollback policy.

Durable import is a separate boundary. When a reviewed handoff package feeds
durable storage, this module adapts exactly one ready import-plan measurement
into `MeasurementRecordImportSource` and
`MeasurementRecordDurableImportRequest`, then delegates mutation to the
Measurement Records durable import pipeline. The adapter does not treat the
import plan as sufficient write authority for bytes on disk; the delegated
pipeline reopens the package member and preflights digest, byte size,
normalized CSV shape, and row count before any storage mutation.

## Artifact Boundaries

The generated package directory and `package-manifest.json` are portable
handoff artifacts. Package contents must use package-relative paths and
validated managed references at the package/export boundary.

Selected stored-record export is a route-local adapter over the existing
Measurement Records read model and record-local receipts. It reads one complete
stored record, requires explicit preview metadata, delegates package writing to
the package writer, keeps linked context reference-only, and does not mutate
Measurement Records storage, refresh read models, infer schema, create
archives, or accept/import packages.

Local writer receipts, inspection HTML, function return values, import-plan
objects, durable-import adapter receipts, retry reviews, and CLI summaries are
local review surfaces unless a later slice explicitly promotes one as a
portable/export artifact. Linked-context entries remain reference-only: the
module can expose selected context references for review, but it does not
package linked payloads, resolve references, restore environments, or import
linked context into durable Measurement Records storage.

## CLI

The CLI remains a local operator surface:

```sh
python -m scopecat.handoff <package-dir>
python -m scopecat.handoff <package-dir> --html-dir <output-dir>
python -m scopecat.handoff --receipt-summary <receipt.json>
```

It opens a package for read-only orientation, optionally writes local
inspection HTML, and summarizes local candidate or durable-import receipts for
continuation review. It does not run package import, approve storage
acceptance or durable import, persist review state, or become a public import
API.

## Historical Candidate Context

Discovery implementation candidates remain historical validation inputs, not
runtime dependencies. The older candidate storage acceptance route remains
only as historical engineering evidence in direct modules:

- `scopecat.handoff.acceptance_preflight`
- `scopecat.handoff.storage_acceptance`
- `scopecat.handoff.import_workflow`

That route proved reviewed destination continuity, no-overwrite checks, local
operator decisions, rollback classification, receipt summary, and retry review
for `measurement_record_directory_candidate_v0`. It is no longer exported from
the top-level `scopecat.handoff` API and should not be extended for durable
Measurement Records import.

## Boundary

This README owns live API orientation. Detailed scope limits live in the
prototype-boundary notes linked above.
