# Discovery Routes

## Status

Navigation index, not an ADR.

Routes group discovery work by durable user workflow and authority boundary.
Use route indexes for current route posture and sequencing unless an index is
explicitly marked retired; use validation results for slice-local evidence.

## Current Routes

| Route | Use For |
| --- | --- |
| [`adoption-routes.md`](adoption-routes.md) | Compare evidence-backed adoption routes by durable user workflow. |
| [`measurement-records/README.md`](measurement-records/README.md) | Measurement records, import/source decisions, storage writing, selected handoff, package use, and source observation. |
| [`measurement-records/import-source-decision.md`](measurement-records/import-source-decision.md) | Current import/source route decisions, deferred decisions, reopen triggers, and next-slice guidance. |
| [`experiment-code/README.md`](experiment-code/README.md) | Experiment-code recording, managed code versions, workspace materialization, and prepared-run code context. |
| [`environment-operation/README.md`](environment-operation/README.md) | Environment declaration, file observation, review bundles, manager command intent, and external result recording. |
| [`calibration-continuation/README.md`](calibration-continuation/README.md) | Calibration continuation, reviewable step state, accepted write handoff, and calibration-derived parameter-state measurement context. |
| [`calibration-continuation/decision.md`](calibration-continuation/decision.md) | Current calibration continuation route decision consolidation, deferred decisions, reopen triggers, and stop rule. |

## Retired Route Notes

| Route | Use For |
| --- | --- |
| [`measurement-records/handoff/README.md`](measurement-records/handoff/README.md) | Retired handoff package route map and historical discovery synthesis; current handoff boundaries live in architecture and module docs. |
| [`measurement-records/handoff/decision.md`](measurement-records/handoff/decision.md) | Retired handoff route decision closeout; preserved for historical deferrals, reopen triggers, and stop-rule context. |

## Related Non-Route Owners

| Owner | Use For |
| --- | --- |
| [`../problem-briefs/README.md`](../problem-briefs/README.md) | Evidence-backed problem framing before choosing a validation question. |
| [`../slices/README.md`](../slices/README.md) | Current discovery slice inventory by route and maturity. |
| [`../synthesis/measurement-context-backlog.md`](../synthesis/measurement-context-backlog.md) | Shared backlog for measurement-context-shaped validation work across routes. |
