# ADR-0011: Allow Selected-Record Batch Package Export Without Batch Import

## Status

ADR status: accepted.

Date: 2026-06-03.

## Context

The route-local package writer can already write packages containing multiple
selected measurements. ADR-0009 allows receiving/import planning over multiple
package measurements without turning that plan into batch durable mutation.

This decision resolves whether the JNY-001 storage-backed selected-record
export path may select more than one complete Measurement Record into one
handoff package. This needs to preserve the same durable record evidence as
single-record export: each selected record must be complete, record-local, and
continuous across read model, creation manifest, writer receipt, primary bytes,
digest, and size.

## Decision

Selected stored Measurement Record export may create one directory-manifest
handoff package containing multiple selected stored records.

Each selected record is validated independently from its record-local read
model, creation manifest, writer receipt, primary-data path, digest, size, and
explicit declared table-preview metadata. The batch export adapter delegates
package-member copying, no-overwrite behavior, manifest writing, package
opening, and package integrity to the existing handoff package writer and
reader.

The batch export request is package-level write authority. It may include
multiple record selections, but it does not authorize durable batch import.
Receiving and durable import remain governed by ADR-0009 and ADR-0013: import
plans may list multiple measurements, while durable handoff import still
mutates exactly one planned measurement per operation.

## Scope

This decision applies to:

- selected stored Measurement Record batch export requests;
- ADR-0006 directory manifest packages;
- record-local evidence validation for every selected record;
- package writer multi-measurement output.

This decision does not apply to:

- durable batch Measurement Records import beyond ADR-0013;
- per-record destination assignment on receiving;
- batch conflict resolution, partial success, rollback, or retry policy;
- recursive linked-context traversal;
- linked-context payload import beyond ADR-0012;
- GUI batch review state.

## Consequences

Source-side users can package several complete stored records together without
weakening record-local evidence checks or inventing a new package format. The
receiving side still stays conservative: a multi-measurement package can be
opened and planned as a batch, but durable storage mutation remains
one-record-at-a-time.

Future work beyond ADR-0013 must still decide whether batch durable import is
worth the additional destination, conflict, partial-success, rollback, and
retry contracts.

## Alternatives Considered

- Option: keep selected stored-record export single-record only. Rejected
  because the writer and receiving plan already support multi-measurement
  package review safely.
- Option: couple batch export to batch durable import. Rejected because
  ADR-0009 explicitly keeps durable mutation one planned measurement at a time.
- Option: allow batch export from arbitrary caller paths. Rejected because
  UC-006 remains the storage-backed product path; direct writer input stays
  route-local.

## Supersession

Supersedes:

- none.

Superseded by:

- none.

## Review Triggers

Revisit this decision when:

- durable import needs multi-record mutation beyond ADR-0013;
- receiving review needs persistent batch destination assignment;
- selected batch export needs package-level context topology;
- linked-context payload import is revisited beyond ADR-0012;
- GUI review needs stable multi-measurement selection state;
- package format changes beyond ADR-0006.

## Related Evidence

- [`ADR-0006-package-format-directory-manifest.md`](ADR-0006-package-format-directory-manifest.md)
- [`ADR-0009-batch-receiving-import-planning.md`](ADR-0009-batch-receiving-import-planning.md)
- [`ADR-0012-defer-linked-context-payload-import.md`](ADR-0012-defer-linked-context-payload-import.md)
- [`ADR-0013-defer-batch-durable-import.md`](ADR-0013-defer-batch-durable-import.md)
- [`../../engineering/prototype-boundaries/handoff.md`](../engineering/prototype-boundaries/handoff.md)
- [`../../engineering/workflow-validation-map.md`](../engineering/workflow-validation-map.md)
- [`../../../tests/prototypes/handoff/test_handoff_selected_record_export.py`](../../tests/prototypes/handoff/test_handoff_selected_record_export.py)
