# DEC-017: Defer Batch Durable Import

## Status

Decision type: architecture.

Decision status: accepted.

Date: 2026-06-03.

Owner: [`../../engineering/prototype-boundaries/handoff-durable-import-storage.md`](../../engineering/prototype-boundaries/handoff-durable-import-storage.md).

## Context

DEC-013 allows receiving/import planning to list multiple package measurements
without storage mutation. DEC-015 allows selected stored-record export to
produce multi-measurement handoff packages. The remaining receiving-side
pressure is whether a reviewed multi-measurement import plan should authorize
one durable batch mutation.

The current handoff durable-import adapter is intentionally one planned
measurement per operation. It delegates mutation to Measurement Records durable
import, which already owns per-record destination identity, no-overwrite
behavior, rollback classification, retry review, and read-model projection.
Turning a multi-measurement plan into one durable operation would require new
contracts for per-record destinations, conflict handling, partial success,
rollback scope, retry grouping, and review state.

## Decision

Do not add batch durable import to the current JNY-001 handoff slice.

Multi-measurement handoff packages may be opened, integrity-observed, reviewed,
and planned together. Durable import remains one planned package measurement
per storage mutation. A multi-measurement import plan is review evidence and
coordination context, not write authority for multiple durable records.

Any future batch durable import must be promoted through a separate decision
and implementation slice that defines, at minimum:

- destination assignment for every planned measurement;
- conflict and no-overwrite behavior per destination;
- whether the batch is one transaction, a coordinated sequence, or an explicit
  partial-success workflow;
- rollback scope and failure classification for each planned measurement;
- retry summary shape for partial and total failures;
- ordering, idempotency, and stale-review requirements;
- receipt and review-state shape for users.

## Scope

This decision applies to:

- DEC-010 directory manifest packages;
- DEC-013 multi-measurement import plans;
- DEC-015 selected stored-record batch package export;
- handoff durable-import adaptation to Measurement Records storage.

This decision does not apply to:

- source-side batch package export;
- non-mutating receiving/import planning;
- repeated manual single-measurement durable imports;
- future GUI workflow state;
- future storage transaction or batch-import contracts.

## Consequences

Users can review and plan multi-measurement packages, but durable storage
mutation stays conservative and auditable. Existing single-record import
rollback and retry behavior remains the only accepted durable mutation path.

The next receiving-side product pressure shifts to archive
packaging/extraction, signed package policy beyond DEC-019, or a future
explicit batch import contract with destination and partial-success semantics.
GUI receiving state projection is governed by DEC-018.

## Alternatives Considered

- Option: implement batch durable import as repeated single-record imports.
  Rejected because that would hide ordering, partial failure, and retry review
  from the user.
- Option: require all-or-nothing batch transaction semantics now. Rejected
  because the current filesystem-backed Measurement Records import has no
  accepted cross-record transaction model.
- Option: block multi-measurement packages. Rejected because package export,
  opening, and import planning can safely handle multi-measurement review
  without mutation.

## Supersession

Supersedes:

- none.

Superseded by:

- none.

## Review Triggers

Revisit this decision when:

- a named workflow requires importing multiple package measurements in one
  reviewed action;
- GUI receiving state can present per-record destination assignment and
  partial-success review;
- Measurement Records gains a cross-record transaction or batch receipt model;
- retry review needs to coordinate multiple failed package measurements;
- storage conflict policy expands beyond new-record no-overwrite behavior.

## Related Evidence And Owners

- [`DEC-013-batch-receiving-import-planning.md`](DEC-013-batch-receiving-import-planning.md)
- [`DEC-015-selected-record-batch-package-export.md`](DEC-015-selected-record-batch-package-export.md)
- [`DEC-018-define-receiving-review-state-contract.md`](DEC-018-define-receiving-review-state-contract.md)
- [`../../engineering/prototype-boundaries/handoff.md`](../../engineering/prototype-boundaries/handoff.md)
- [`../../engineering/prototype-boundaries/handoff-durable-import-storage.md`](../../engineering/prototype-boundaries/handoff-durable-import-storage.md)
- [`../../engineering/workflow-validation-map.md`](../../engineering/workflow-validation-map.md)
- [`../../../src/scopecat/handoff/durable_import.py`](../../../src/scopecat/handoff/durable_import.py)
- [`../../../tests/prototypes/handoff/test_handoff_durable_import_adapter.py`](../../../tests/prototypes/handoff/test_handoff_durable_import_adapter.py)
