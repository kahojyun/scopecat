# DEC-013: Allow Batch Import Planning Without Batch Durable Mutation

## Status

Decision type: architecture.

Decision status: accepted.

Date: 2026-06-03.

Owner: [`../../engineering/prototype-boundaries/handoff.md`](../../engineering/prototype-boundaries/handoff.md).

## Context

Handoff packages can contain more than one selected measurement. The package
writer and opener already validate and project multiple measurements, and the
receiving/import-plan path can review a whole package without storage mutation.

The next boundary pressure is whether selecting multiple package measurements
should authorize durable batch import. Durable Measurement Records import still
owns one new record at a time, with per-record destination identity,
no-overwrite behavior, rollback classification, and retry review. Turning a
multi-measurement import plan into one batch mutation would require a separate
contract for partial success, per-record retry, destination conflicts, rollback
scope, and user review state.

## Decision

The handoff receiving/import-plan path may produce a non-mutating import plan
for multiple package measurements. `all_measurements` may expand to all opened
package measurement ids, and `selected_measurements` may name more than one
measurement id.

The durable handoff import adapter remains single-measurement only. DEC-017
keeps a ready multi-measurement import plan as review evidence and planning
output, not durable batch mutation authority. Durable import must continue to
require exactly one planned measurement before building a
`MeasurementRecordDurableImportRequest`.

## Scope

This decision applies to:

- DEC-010 directory manifest handoff packages;
- receiving gate and import-plan output over multi-measurement packages;
- route-local durable import adaptation from handoff import plans.

This decision does not apply to:

- batch durable Measurement Records mutation beyond DEC-017;
- per-record destination assignment for batches;
- batch conflict resolution, rollback, retry, or partial-success policy;
- selected stored Measurement Record batch export authority;
- GUI batch review state.

## Consequences

Receiving users can review and plan multiple package measurements together
without implying a batch write. Durable import stays conservative and
per-record, preserving the already validated no-overwrite and retry behavior.

Future batch durable import work beyond DEC-017 must define per-measurement
destinations, conflict handling, partial-success reporting, rollback
expectations, and retry semantics before allowing multi-record mutation.

## Alternatives Considered

- Option: block multi-measurement import plans. Rejected because package
  review can safely list multiple package measurements without mutation.
- Option: immediately turn multi-measurement plans into batch durable import.
  Rejected because durable storage semantics are currently validated
  one-record-at-a-time only.
- Option: implicitly split a batch plan into many durable imports. Rejected
  because that would hide destination, conflict, retry, and partial-success
  choices from review.

## Supersession

Supersedes:

- none.

Superseded by:

- none.

## Review Triggers

Revisit this decision when:

- receiving review needs batch destination assignment;
- durable import needs per-record partial-success summaries;
- GUI review needs persistent multi-measurement selection state;
- selected stored Measurement Record export needs broader batch package topology;
- retry review needs to coordinate more than one failed measurement.

## Related Evidence And Owners

- [`DEC-010-package-format-directory-manifest.md`](DEC-010-package-format-directory-manifest.md)
- [`DEC-017-defer-batch-durable-import.md`](DEC-017-defer-batch-durable-import.md)
- [`../../engineering/prototype-boundaries/handoff.md`](../../engineering/prototype-boundaries/handoff.md)
- [`../../engineering/workflow-validation-map.md`](../../engineering/workflow-validation-map.md)
- [`../../../tests/prototypes/handoff/test_handoff_engineering_prototype_import_plan.py`](../../../tests/prototypes/handoff/test_handoff_engineering_prototype_import_plan.py)
- [`../../../tests/prototypes/handoff/test_handoff_durable_import_adapter.py`](../../../tests/prototypes/handoff/test_handoff_durable_import_adapter.py)
