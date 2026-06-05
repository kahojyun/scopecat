# Handoff Module

## Status

Current implementation owner for Scopecat-authored handoff package use and
durable Measurement Records handoff import adaptation.
This module owns route-local package and receiving behavior for JNY-001 Share A
Selected Measurement; it does not own Measurement Record creation, run
recording, running updates, or post-run results review.

This module exposes route-local Python entrypoints over accepted handoff
behavior. Boundary details live in the engineering boundary notes linked below.

For workflow and implementation ownership, start from
[`../../../docs/engineering/workflow-validation-map.md`](../../../docs/engineering/workflow-validation-map.md)
and
[`../../../docs/engineering/implementation-register.md`](../../../docs/engineering/implementation-register.md).
For accepted boundaries, start from
[`../../../docs/engineering/prototype-boundaries/handoff.md`](../../../docs/engineering/prototype-boundaries/handoff.md)
and
[`../../../docs/engineering/prototype-boundaries/handoff-durable-import-storage.md`](../../../docs/engineering/prototype-boundaries/handoff-durable-import-storage.md).

## Current Surfaces

Package writer:

- `export_selected_measurement_record_from_request(request, storage_root=..., package_root=...)`
- `export_selected_measurement_record_batch_from_request(request, storage_root=..., package_root=...)`

Read-only package use and local review:

- `open_package(package_dir)`

Receiving-side read-only planning:

- `observe_package_integrity(package_dir)`
- `run_receiving_gate_from_request(request, package_dir=...)`
- `build_import_plan(request, receiving_gate=...)`

Durable Measurement Records import adaptation:

- `run_handoff_durable_import_from_plan(request, import_plan=..., storage_root=...)`

The top-level module exports active operation entrypoints and caller-supplied
request/value objects needed to invoke those operations. Route projection,
run/result, direct writer, context-summary, durable-request builder, and
inspection helpers remain importable from their owning submodules when tests or
route-local integrations need them, but they are not package-root contracts.
`HandoffError` and
`HandoffContractError` remain the package-root error types. Modules with
leading underscores are route-private implementation modules.

## Boundary Split

Raw manifest dictionaries are validated at the package boundary. After that,
manifest preview classification, opener internals, review findings, and
package projections consume typed route-local manifest fragments. Raw workflow
dictionaries are not accepted as receiving, import-plan, selected-export,
archive, or durable-import operation inputs; those operations compose typed
route-local request and run objects.

`write_package_from_source(...)` is the route-local typed writer primitive.
`write_package(...)` remains a compatibility adapter for raw package-writer
input. The writer accepts explicit caller-declared package ids, measurement
ids, source paths, digests, sizes, and linked-context facts. Those identifiers
are reviewed package-input facts only; they are not durable Scopecat
Measurement Record identity and do not replace record-local read models,
creation manifests, or writer receipts.

`build_import_plan(...)` is a non-mutating plan. It names package members that
could be considered for later acceptance, but accepts no destination path,
performs no conflict detection, writes no storage records, and does not decide
final storage schema or rollback policy. It may list one or more package
measurements; durable handoff import remains one planned measurement per
storage mutation.

Durable import is a separate boundary. When a reviewed handoff package feeds
durable storage, this module adapts exactly one ready import-plan measurement
into `MeasurementRecordImportSource` and
`MeasurementRecordDurableImportRequest`, then delegates mutation to the
Measurement Records durable import operation. The adapter does not treat the
import plan as sufficient write authority for bytes on disk; the delegated
operation reopens the package member and preflights digest, byte size,
normalized CSV shape, and row count before any storage mutation.
Under DEC-025 this path creates a new Measurement Record only; it does not
update existing records, merge primary data, replace manifests, or publish a
final storage schema.

Durable-import receipts include compact local state and `block_reason` fields.
They do not approve retry, reuse stale plans, skip destination checks, or
bypass package revalidation.

Public receiving, import-planning, and durable-import API functions promote
route contract failures to `HandoffContractError`, which remains
`ValueError`-compatible for existing callers. `to_diagnostic()` returns a
local operator error diagnostic with operation, code, and message. That
diagnostic is not a portable/export artifact, retry authorization, package
acceptance, or public error schema.

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
objects, and durable-import adapter receipts are local review surfaces unless a
later slice explicitly promotes one as a portable/export artifact.

Selected-record export receipts keep compact `block_reason` state for blocked
local runs. The lower-level export path checks that the selected read model
matches the request, record-local creation manifest, and writer receipt before
writing a package, but it does not project, refresh, repair, or mutate
Measurement Records storage.

`export_selected_measurement_record_with_preflight_refresh()` composes that
lower-level export check with the Measurement Records read-model refresh route.
It first runs selected export as a freshness preflight; when the read model is
missing, invalid, or stale, it delegates an approved read-model refresh and then
retries export if refresh succeeds. The composed receipt records the initial
export, refresh receipt or refresh contract error, final export, and compact
`block_reason` state. This is the product-shaped path for a user-transparent
cache refresh; it still does not repair primary data, replace record manifests,
mutate writer/finalization receipts, or import/accept packages.

Receiving gate and import-plan receipts keep compact `block_reason` state for
blocked local runs. They do not approve retry, accept packages, or mutate
storage.

This module observes declared digest integrity, but it does not verify external
authenticity, package provenance, trusted source, or trust-gated import policy.
That limitation is documented in the accepted decisions rather than repeated
as receipt fields.

Archive-backed durable import, archive bytes as package authority, and broader
archive semantics remain deferred under DEC-020, while DEC-021 accepts safe zip
archive materialization into a DEC-010 directory package of record and DEC-024
accepts safe zip archive creation from an openable DEC-010 directory package.
This module writes and opens directory manifest packages, can create a zip
transport archive from one, and can materialize a zip transport archive into a
staging directory; it still does not verify authenticity or trust, import
directly from archive bytes, or treat archive bytes as package authority.
`materialize_handoff_archive_package_from_request()` materializes zip
transport archives after path, member, manifest, collision, and package-open
checks. `create_handoff_archive_package_from_request()` creates zip transport
archives after package-open, member, symlink, metadata, collision, and
no-overwrite checks.

The generic package writer can package explicitly declared linked-context
payload files under `context/` after source digest and size preflight. Opened
packages expose those entries as `packaged_payload`, and integrity observation
checks them as declared package members. Import planning and durable import
still do not import linked-context payloads under DEC-016. Selected
stored-record export uses the same package-member path only when its export
request declares a source path under the selected record directory, a
`context/` package path, digest, and byte size.

## Historical Candidate Context

Discovery implementation candidates remain historical validation inputs, not
runtime dependencies. The older candidate storage acceptance route has been
retired from installable `src` modules and remains only as historical
engineering evidence in git history and archived notes.

That route proved reviewed destination continuity, no-overwrite checks, local
operator decisions, and rollback classification for
`measurement_record_directory_candidate_v0`. It should not be restored or
extended as the durable Measurement Records import path.

## Boundary

This README owns live API orientation. Detailed scope limits live in the
engineering boundary notes linked above.
