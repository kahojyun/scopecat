# Architecture Notes

## Status

Engineering and architecture navigation.

This directory owns durable implementation-boundary notes after discovery
evidence has started moving into route-local engineering work. It is not public
user documentation and does not replace discovery validation evidence.

For top-down implementation orientation, start with
[`../engineering/workflow-validation-map.md`](../engineering/workflow-validation-map.md)
and [`../engineering/vertical-slice-register.md`](../engineering/vertical-slice-register.md),
then open the route-specific decision linked here and the owning module README.

## Current Notes

Accepted boundary navigation lives in [`boundaries/README.md`](boundaries/README.md).

| Document | Use For |
| --- | --- |
| [`boundaries/environment-operation.md`](boundaries/environment-operation.md) | Canonical accepted environment-operation implementation boundary and next decision gate. |
| [`boundaries/measurement-records-creation-lifecycle.md`](boundaries/measurement-records-creation-lifecycle.md) | Decisions and implementation checkpoints for durable measurement-record creation, writer integration, read view, finalization, read-model projection/refresh/catalog, in-progress inspection, operator review, and saved review receipts. |
| [`boundaries/measurement-records-legacy-run-storage.md`](boundaries/measurement-records-legacy-run-storage.md) | Accepted first user-facing legacy storage workflow for declared legacy runs, converted-primary attach, references, inventory, and local review. |
| [`boundaries/handoff.md`](boundaries/handoff.md) | Canonical accepted handoff package-use implementation boundary, with historical candidate-storage checkpoints called out separately. |
| [`boundaries/handoff-durable-import-storage.md`](boundaries/handoff-durable-import-storage.md) | Accepted first durable import/storage boundary: approved normalized import creates a new measurement record through the Measurement Records pipeline. |
| [`boundaries/parameter-state.md`](boundaries/parameter-state.md) | Canonical accepted parameter-state route-local implementation boundary for adapter import review, storage read/write, selection context, and prepared-run review composition. |

## Historical Notes

Archived note navigation lives in [`archive/README.md`](archive/README.md).

| Document | Use For |
| --- | --- |
| [`archive/environment-operation-prototype-plan.md`](archive/environment-operation-prototype-plan.md) | Frozen historical environment-operation prototype plan: objective, scope, non-claims, and stop conditions. |
| [`archive/environment-operation-prototype-readiness.md`](archive/environment-operation-prototype-readiness.md) | Frozen readiness checkpoint that ended the broad environment-operation prototype line. |
| [`archive/handoff-prototype-plan.md`](archive/handoff-prototype-plan.md) | Frozen historical handoff prototype plan: objective, scope, fixture policy, stop conditions, and promotion criteria. |
| [`archive/handoff-prototype-readiness.md`](archive/handoff-prototype-readiness.md) | Frozen readiness checkpoint that ended the broad handoff prototype line. |
| [`archive/handoff-candidate-storage-acceptance.md`](archive/handoff-candidate-storage-acceptance.md) | Legacy first handoff candidate storage-acceptance implementation slice, rollback rule, and deferred storage decisions. |
| [`archive/handoff-storage-import-requirements-synthesis.md`](archive/handoff-storage-import-requirements-synthesis.md) | Historical decision-prep synthesis for what handoff storage/import could do before durable measurement-record creation existed. |
