# Architecture Notes

## Status

Engineering and architecture navigation.

This directory owns durable implementation-boundary notes after discovery
evidence has started moving into route-local engineering work. It is not public
user documentation and does not replace discovery validation evidence.

## Current Notes

| Document | Use For |
| --- | --- |
| [`environment-operation/engineering-prototype-plan.md`](environment-operation/engineering-prototype-plan.md) | Frozen historical environment-operation prototype plan: objective, scope, non-claims, and stop conditions. |
| [`environment-operation/engineering-prototype-readiness.md`](environment-operation/engineering-prototype-readiness.md) | Frozen readiness checkpoint that ended the broad environment-operation prototype line. |
| [`environment-operation/engineering-prototype-promotion-decision.md`](environment-operation/engineering-prototype-promotion-decision.md) | Canonical accepted environment-operation implementation boundary and next decision gate. |
| [`measurement-records/creation-lifecycle-decision.md`](measurement-records/creation-lifecycle-decision.md) | Decisions and implementation checkpoints for durable measurement-record creation, writer integration, read view, receipt-based finalization, and derived read-model projection. |
| [`handoff/engineering-prototype-promotion-decision.md`](handoff/engineering-prototype-promotion-decision.md) | Canonical accepted handoff package-use implementation boundary, with historical candidate-storage checkpoints called out separately. |
| [`handoff/durable-import-storage-decision.md`](handoff/durable-import-storage-decision.md) | Accepted first durable import/storage boundary: approved normalized import creates a new measurement record through the Measurement Records pipeline. |

## Historical Notes

| Document | Use For |
| --- | --- |
| [`handoff/engineering-prototype-plan.md`](handoff/engineering-prototype-plan.md) | Frozen historical handoff prototype plan: objective, scope, fixture policy, stop conditions, and promotion criteria. |
| [`handoff/engineering-prototype-readiness.md`](handoff/engineering-prototype-readiness.md) | Frozen readiness checkpoint that ended the broad handoff prototype line. |
| [`handoff/storage-acceptance-decision.md`](handoff/storage-acceptance-decision.md) | Legacy first handoff candidate storage-acceptance implementation slice, rollback rule, and deferred storage decisions. |
| [`handoff/storage-import-requirements-synthesis.md`](handoff/storage-import-requirements-synthesis.md) | Historical decision-prep synthesis for what handoff storage/import could do before durable measurement-record creation existed. |
