# DEC-025: Defer Existing-Record Update And Final Storage Schema For JNY-001

## Status

Decision type: architecture.

Decision status: accepted.

Date: 2026-06-04.

Owner: [`../../engineering/prototype-boundaries/handoff.md`](../../engineering/prototype-boundaries/handoff.md).

## Context

JNY-001 Share A Selected Measurement now has a production vertical slice
candidate for portable measurement handoff: export one complete stored
Measurement Record, transfer it as a DEC-010 directory manifest package with
optional zip transport, review it on the receiving side, plan import, and
durably import exactly one package measurement into a second storage root.

That slice already proves the valuable user path without updating an existing
record. Selected-record export reads one complete stored record and writes a
package without mutating source storage. Receiving durable import creates one
new Measurement Record by delegating to the Measurement Records durable import
pipeline.

Existing-record update, merge import, manifest replacement, canonical primary
data compaction, and final storage schema publication would broaden the slice
from portable handoff into durable record lifecycle redesign. Those concerns
need explicit conflict, provenance, rollback, read-model, and user-review
contracts before they can safely affect production readiness.

## Decision

Keep JNY-001 production-readiness hardening new-record-only for durable import
and source-storage-read-only for selected-record export.

Selected stored-record export may read record-local read models, creation
manifests, writer receipts, finalization receipts, and primary data. It must
not update, repair, merge, compact, or replace source Measurement Records
storage while producing a handoff package.

Handoff durable import may adapt one ready package measurement into the
Measurement Records durable import pipeline for creation of a new record. It
must not import into an existing record, attach to a pre-created shell, replace
an existing manifest, merge primary data, or publish a final public storage
schema.

The current storage schema remains a route-local prototype schema for the
validated vertical slice. It is stable enough for regression coverage and local
workflow review, but not a published product schema, database/index contract,
or shared cross-route domain model.

Any future existing-record update/import or final storage schema work must be
promoted through a separate named use case or decision that defines, at
minimum:

- how an existing target record is selected and reviewed;
- conflict behavior when package facts disagree with existing record facts;
- whether updates append evidence, replace manifests, merge primary data, or
  write new derived projections only;
- rollback and retry behavior for partial updates;
- source provenance and audit receipt shape;
- read-model refresh and stale-review handling after mutation;
- user-facing review language for update versus new-record import.

## Scope

This decision applies to:

- UC-006 selected stored Measurement Record export;
- JNY-001 Share A Selected Measurement production vertical slice candidate;
- handoff durable import into Measurement Records storage;
- Measurement Records storage-readiness posture required by the handoff slice.

This decision does not apply to:

- existing-record update workflows outside JNY-001;
- Measurement Records update evidence already accepted for in-progress local
  records;
- final public storage schema publication;
- database/index design;
- shared cross-route domain model extraction;
- GUI-owned receiving review state.

## Consequences

Production-readiness work can now harden the current JNY-001 path without
silently expanding into record merge semantics. This keeps the user-visible
handoff behavior predictable: source export is read-only, receiving import
creates a new record, and no existing durable record is modified by handoff.

The tradeoff is that users who want to update an existing record from a package
must use a future workflow. That workflow should be designed as an explicit
record lifecycle action rather than hidden inside package receiving.

## Alternatives Considered

- Option: treat received packages as updates to existing records when record ids
  match. Rejected because id equality is not enough review authority to mutate
  existing storage.
- Option: let selected-record export repair stale or incomplete source records.
  Rejected because export is a packaging workflow; read-model refresh is already
  delegated explicitly and source repair needs its own ownership.
- Option: publish the current route-local storage layout as final schema now.
  Rejected because shared domain extraction, existing-record update, context
  artifact import, and GUI review state remain unsettled.

## Supersession

Supersedes:

- none.

Superseded by:

- none.

## Review Triggers

Revisit this decision when:

- a named user workflow requires importing a package into an existing record;
- Measurement Records accepts manifest replacement or primary-data merge
  semantics;
- GUI receiving review needs to present update-versus-create choices;
- final public storage schema publication becomes the next product target;
- shared domain model extraction needs stable cross-route record lifecycle
  semantics.

## Related Evidence And Owners

- [`../../engineering/prototype-boundaries/handoff.md`](../../engineering/prototype-boundaries/handoff.md)
- [`../../engineering/prototype-boundaries/handoff-durable-import-storage.md`](../../engineering/prototype-boundaries/handoff-durable-import-storage.md)
- [`../../engineering/prototype-boundaries/measurement-records-creation-lifecycle.md`](../../engineering/prototype-boundaries/measurement-records-creation-lifecycle.md)
- [`../../engineering/workflow-validation-map.md`](../../engineering/workflow-validation-map.md)
- [`../../../src/scopecat/handoff/selected_record_export.py`](../../../src/scopecat/handoff/selected_record_export.py)
- [`../../../src/scopecat/handoff/durable_import.py`](../../../src/scopecat/handoff/durable_import.py)
- [`../../../tests/integration/handoff/test_jny001_single_measurement_handoff.py`](../../../tests/integration/handoff/test_jny001_single_measurement_handoff.py)
