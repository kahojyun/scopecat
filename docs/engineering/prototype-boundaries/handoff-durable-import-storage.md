# Handoff Durable Import Boundary

## Status

Accepted engineering-prototype boundary.

## Purpose

Own the cross-owner adapter boundary where one reviewed handoff package
measurement becomes one new durable Measurement Record.

Package writing, opening, receiving gates, and non-mutating import plans are
owned by [`handoff.md`](handoff.md). Durable Measurement Records storage is
owned by [`measurement-records-storage.md`](measurement-records-storage.md).

## Boundary

The adapter flow is:

```text
ready handoff import plan
  -> approved durable import request with destination record_id
  -> MeasurementRecordImportSource
  -> Measurement Records by-id import facade
  -> local handoff durable-import receipt
```

The adapter:

- imports exactly one selected planned measurement per operation;
- requires an approved `HandoffDurableImportRequest`;
- requires a caller-declared destination `record_id` for the new durable
  record;
- maps reviewed package facts to `MeasurementRecordImportSource` with
  `source_kind="handoff_package"`;
- delegates canonical record-local path construction, creation,
  primary-data writing, primary-table summary, finalization, read-model writing,
  no-overwrite handling, and rollback classification to
  `scopecat.measurement_records`;
- returns a local handoff durable-import receipt that records package,
  selected measurement, destination record id, and durable-import
  classification.

The import plan is not write authority. Before mutation, the delegated
Measurement Records operation reopens the package member through the package
directory content root and validates digest, byte size, normalized CSV shape,
format, and row count.

## Source Facts

The adapter may consume only reviewed package facts produced by the open
package and ready import-plan path:

| Durable Import Field | Handoff Source |
| --- | --- |
| `source_kind` | `handoff_package` |
| `source_id` | opened package id |
| `source_item_id` | selected package measurement id |
| `content_ref` | selected measurement primary-data package path |
| `declared_digest` | observed package primary-data digest after integrity observation |
| `size_bytes` | observed primary-data byte size, requiring agreement with declared size when present |
| `rows_recorded` | opened primary table row count |
| `primary_data_format` | selected measurement primary format, currently `csv_table` |
| `label`, `experiment_type` | selected package measurement metadata |
| `creation_source_kind` | `handoff` |

Linked context remains review context. Durable import keeps packaged
linked-context payloads out of Measurement Records storage until a separate
context artifact import contract exists.

## Failure Shape

Handoff preserves delegated storage outcomes in its local receipt instead of
reclassifying Measurement Records storage semantics.

Expected classifications include:

| Classification | Meaning |
| --- | --- |
| `imported_new_record` | Creation, primary-data write, primary-table summary, finalization, and read-model write completed. |
| `blocked_before_import` | Approval, source facts, destination record, or preflight validation blocked before storage mutation. |
| `rolled_back_after_import_failure` | Mutation started, then a synchronous failure occurred before completion and best-effort cleanup ran. |
| `import_failed_after_partial_commit` | A later synchronous failure occurred after a step that the wrapper cannot safely undo. |

Rollback remains best-effort process-local cleanup. It is not crash recovery,
transactional durability, stale-lock cleanup, or concurrent storage-root
protection.

## Artifact And Storage Authority

The handoff package directory and `package-manifest.json` are portable handoff
artifacts. Durable Measurement Records storage is owned by
`scopecat.measurement_records`.

Local handoff durable-import receipts are local review surfaces. They are not
portable handoff artifacts, retry approval, persistent GUI state,
destination-record freshness proof, or storage mutation authority.

## Out Of Scope

This boundary does not accept:

- importing multiple measurements in one durable operation;
- importing into an existing record or attaching to a pre-created shell;
- primary-data merge, compaction, or append visibility as canonical import
  behavior;
- final record-id generation policy;
- manifest replacement or canonical-current-state manifest updates;
- linked-context payload materialization;
- archive extraction or archive-backed durable import;
- external authenticity or package trust policy;
- adapter discovery, drop-folder protocol, service API, or stable public
  adapter API;
- conflict policy beyond new-record no-overwrite behavior;
- lock identity, stale-lock cleanup, crash recovery, or concurrent writer
  behavior;
- public storage schema, export schema, database index, or GUI import review
  state.

## Advancement Questions

Advance this boundary only when a named workflow requires broader durable
handoff import behavior, such as batch durable import, linked-context payload
import, existing-record update/import, GUI durable review state, or stronger
storage recovery.
