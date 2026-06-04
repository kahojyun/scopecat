# Handoff Prototype Module

## Status

Current engineering-prototype implementation owner for Scopecat-authored
handoff package use and durable Measurement Records handoff import adaptation.
This module owns route-local package and receiving behavior for JNY-001 Share A
Selected Measurement; it does not own Measurement Record creation, adoption,
running updates, or completed-record finalization.

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
- `export_selected_measurement_record_batch_from_request(request, storage_root=..., package_root=...)`
- `export_selected_measurement_record_batch(source, storage_root=..., package_root=...)`
- `current_handoff_compatibility_contract()`

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
receiving/import run objects, durable-import receipt/retry summaries, and
`HandoffError` / `HandoffContractError` diagnostics. Modules with leading
underscores are route-private implementation modules.

## Boundary Split

Raw manifest dictionaries are validated at the package boundary. After that,
manifest preview classification, opener internals, review findings, and
package projections consume typed route-local manifest fragments. Raw workflow
dictionaries are accepted only at public `run_*` edge adapters; internal
composition should pass typed route-local request and run objects.

`write_package(...)` is the route-local writer primitive. It accepts explicit
caller-declared package ids, measurement ids, source paths, digests, sizes, and
linked-context facts. Those identifiers are reviewed package-input facts only;
they are not durable Scopecat Measurement Record identity and do not replace
record-local read models, creation manifests, or writer receipts.

`run_import_plan(...)` is a non-mutating plan. It names package members that
could be considered for later acceptance, but accepts no destination path,
performs no conflict detection, writes no storage records, and does not decide
final storage schema or rollback policy. It may list one or more package
measurements; durable handoff import remains one planned measurement per
storage mutation.

Durable import is a separate boundary. When a reviewed handoff package feeds
durable storage, this module adapts exactly one ready import-plan measurement
into `MeasurementRecordImportSource` and
`MeasurementRecordDurableImportRequest`, then delegates mutation to the
Measurement Records durable import pipeline. The adapter does not treat the
import plan as sufficient write authority for bytes on disk; the delegated
pipeline reopens the package member and preflights digest, byte size,
normalized CSV shape, and row count before any storage mutation.
Under DEC-025 this path creates a new Measurement Record only; it does not
update existing records, merge primary data, replace manifests, or publish a
final storage schema.

Durable-import receipts and summaries include local `durable_import_review`
guidance, plus summary `block_reason` and `retry_requires` fields. This is
local review guidance only; it does not approve retry, reuse stale plans, skip
destination checks, or bypass package revalidation.

Public receiving, import-planning, and durable-import API functions promote
route contract failures to `HandoffContractError`, which remains
`ValueError`-compatible for existing callers. `to_diagnostic()` returns a
local operator error diagnostic with operation, code, and message. That
diagnostic is not a portable/export artifact, retry authorization, package
acceptance, or public error schema.

`current_handoff_compatibility_contract()` returns a read-only local snapshot
of the current route schemas, policy fields, local artifact postures, and
explicit non-claims for this production vertical slice. The snapshot is a
review contract for the current route-local behavior; it does not publish a
public SDK, final package format, archive contract, authenticity/trust policy, or
portable error schema.

## Artifact Boundaries

The generated package directory and `package-manifest.json` are portable
handoff artifacts. Package contents must use package-relative paths and
validated managed references at the package/export boundary.

Selected stored-record export is a route-local adapter over the existing
Measurement Records read model and record-local receipts. It reads one complete
stored record, requires explicit preview metadata, delegates package writing to
the package writer, may package explicitly declared record-local linked-context
payloads under `context/`, and does not mutate Measurement Records storage,
repair source records, infer schema, create archives, or accept/import
packages. The preflight composition may delegate read-model refresh, but export
itself remains source-storage-read-only under DEC-025.
Recorded linked references remain review references; they are not file-copy
authority by themselves.

Selected stored-record batch export uses the same storage-backed authority for
each selected record and writes one multi-measurement package. Batch export is
source-side package creation only; durable handoff import remains one planned
measurement per storage mutation under DEC-017.

For the normal JNY-001 Share A Selected Measurement path, selected stored-record
export is the storage-backed entrypoint. Direct package-writer input remains an
adapter or engineering route for already-reviewed normalized data, not a
user-facing shortcut around Measurement Records storage.

Local writer receipts, inspection HTML, function return values, import-plan
objects, durable-import adapter receipts, retry reviews, and CLI summaries are
local review surfaces unless a later slice explicitly promotes one as a
portable/export artifact.

Selected-record export receipts include `export_review` guidance that
classifies successful transfer review or blocked retry review. This is local
review guidance only; it does not approve retry, mutate storage, or refresh
read models.

Selected-record export receipts also include `read_model_freshness_review`
guidance. This review records whether read-model evidence was fresh enough for
export, blocked because it was missing, invalid, stale, incomplete, or
out-of-scope, or was not checked before approval. The export path reports the
required retry evidence but does not project, refresh, repair, or mutate
Measurement Records storage.

`export_selected_measurement_record_with_preflight_refresh()` composes that
lower-level export check with the Measurement Records read-model refresh route.
It first runs selected export as a freshness preflight; when the read model is
missing, invalid, or stale, it delegates an approved read-model refresh and then
retries export if refresh succeeds. The composed receipt records the initial
export review, refresh receipt or refresh contract error, final export, and
preflight review. This is the product-shaped path for a user-transparent cache
refresh; it still does not repair primary data, replace record manifests, mutate
writer/finalization receipts, or import/accept packages.

Receiving gate and import-plan receipts include `receiving_review` and
`import_plan_review` guidance that classifies successful continuation or
blocked retry review. This is local review guidance only; it does not approve
retry, accept packages, or mutate storage.

Receiving review state is currently a derived local projection over those
receipts under DEC-018. `project_handoff_receiving_review_state()` composes
typed receiving-gate, import-plan, durable-import summary, retry-review, and
error diagnostic evidence into a `local_receiving_review_state_projection`.
DEC-023 allows `write_handoff_receiving_review_state_receipt()` to persist that
projection as a no-overwrite local JSON receipt for review continuity. This
module still does not create GUI-owned review state, package acceptance, retry
authorization, or mutation authority.

This module observes declared digest integrity and emits explicit non-claims,
but it does not verify external authenticity, package provenance, trusted
source, or trust-gated import policy.

Archive-backed durable import, archive bytes as package authority, and broader
archive semantics remain deferred under DEC-020, while DEC-021 accepts safe zip
archive materialization into a DEC-010 directory package of record and DEC-024
accepts safe zip archive creation from an openable DEC-010 directory package.
This module writes and opens directory manifest packages, can create a zip
transport archive from one, and can materialize a zip transport archive into a
staging directory; it still does not verify authenticity or trust, import
directly from archive bytes, or treat archive bytes as package authority.
`current_handoff_archive_materialization_contract()` and
`review_handoff_archive_materialization_contract()` expose local contract
review for archive materialization posture. `materialize_handoff_archive_package()`
and `materialize_handoff_archive_package_from_request()` materialize zip
transport archives after path, member, manifest, collision, and package-open
checks. `create_handoff_archive_package()` and
`create_handoff_archive_package_from_request()` create zip transport archives
after package-open, member, symlink, metadata, collision, and no-overwrite
checks.

The generic package writer can package explicitly declared linked-context
payload files under `context/` after source digest and size preflight. Opened
packages expose those entries as `packaged_payload`, and integrity observation
checks them as declared package members. Import planning and durable import
still do not import linked-context payloads under DEC-016. Selected
stored-record export uses the same package-member path only when its export
request declares a source path under the selected record directory, a
`context/` package path, digest, and byte size.

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

`summarize_jny001_operator_smoke()` provides a compact read-only operator
summary over the current JNY-001 vertical slice receipts: selected stored-record
export, zip transport creation, zip materialization, receiving review, import
planning, receiving review-state receipt materialization, and durable new-record
import. It is a local smoke summary only; it does not execute the workflow,
grant mutation authority, create a portable artifact, or define a public SDK
contract.

When `--receipt-summary` sees a handoff contract error, the CLI writes the
local `HandoffErrorDiagnostic` JSON to stderr and exits nonzero. This is local
operator guidance for review; it is not a portable/export artifact or public
CLI error contract.

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
