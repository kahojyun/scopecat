# Discovery Routes

## Status

Discovery route navigation index.

Routes group discovery work by durable user workflow and authority boundary.
Use route indexes for discovery posture and validation sequencing unless an
index is explicitly marked retired; use validation results for slice-local
evidence. Once a route has live engineering ownership, use
[`../../engineering/workflow-validation-map.md`](../../engineering/workflow-validation-map.md)
for workflow sequencing and
[`../../engineering/vertical-slice-register.md`](../../engineering/vertical-slice-register.md)
for implementation ownership.

## Current Routes

| Route | Use For |
| --- | --- |
| [`adoption-routes.md`](adoption-routes.md) | Compare evidence-backed adoption routes by durable user workflow. |
| [`../../engineering/workflow-validation-map.md`](../../engineering/workflow-validation-map.md) | Current workflow sequencing after discovery evidence moves toward implementation. |
| [`../../engineering/vertical-slice-register.md`](../../engineering/vertical-slice-register.md) | Current accepted implementation slice ownership. |
| [`measurement-records/README.md`](measurement-records/README.md) | Measurement records, import/source decisions, storage writing, selected handoff, package use, and source observation. |
| [`measurement-records/import-source-decision.md`](measurement-records/import-source-decision.md) | Current import/source route decisions, deferred decisions, reopen triggers, and next-slice guidance. |
| [`measurement-records/legacy-brownfield-adoption-decision.md`](measurement-records/legacy-brownfield-adoption-decision.md) | Current post-run-first legacy adoption route decisions, deferred decisions, reopen triggers, and stop rule. |
| [`measurement-context/README.md`](measurement-context/README.md) | Resolved measurement-record context-link comparison and remaining measurement-context support-family posture. |
| [`experiment-code/README.md`](experiment-code/README.md) | Experiment-code recording, managed code versions, workspace materialization, and prepared-run code context. |
| [`environment-operation/README.md`](environment-operation/README.md) | Environment declaration, file observation, review bundles, manager command intent, and external result recording. |
| [`parameter-state/README.md`](parameter-state/README.md) | Parameter-state management, adapter import review, storage read/write, selection context, and prepared-run review composition. |
| [`setup-binding/README.md`](setup-binding/README.md) | Setup-binding snapshots, generated line/readout views, measurement run-start setup-context references, and binding-change attention. |
| [`calibration-continuation/README.md`](calibration-continuation/README.md) | Calibration continuation, reviewable step state, accepted write handoff, and calibration-derived parameter-state measurement context. |
| [`calibration-continuation/decision.md`](calibration-continuation/decision.md) | Current calibration continuation route decision consolidation, deferred decisions, reopen triggers, and stop rule. |
| [`selected-reference/README.md`](selected-reference/README.md) | Selected-reference context comparison, recorded-code comparison, and objective comparison findings. |

## Retired Route Notes

| Route | Use For |
| --- | --- |
| [`../archive/measurement-records-handoff-route/README.md`](../archive/measurement-records-handoff-route/README.md) | Retired handoff package route map and historical discovery synthesis; current handoff boundaries live in engineering prototype-boundary and module docs. |
| [`../archive/measurement-records-handoff-route/decision.md`](../archive/measurement-records-handoff-route/decision.md) | Retired handoff route decision closeout; preserved for historical deferrals, reopen triggers, and stop-rule context. |

## Related Non-Route Owners

| Owner | Use For |
| --- | --- |
| [`../problem-briefs/README.md`](../problem-briefs/README.md) | Evidence-backed problem framing before choosing a validation question. |
| [`../slices/README.md`](../slices/README.md) | How to use discovery slice results as evidence. |
| [`../archive/slice-inventory.md`](../archive/slice-inventory.md) | Historical flat discovery slice inventory. |
| [`../synthesis/measurement-context-backlog.md`](../synthesis/measurement-context-backlog.md) | Shared backlog for measurement-context-shaped validation work across routes. |
| [`../problem-briefs/setup-binding.md`](../problem-briefs/setup-binding.md) and [`../slices/setup-binding/setup-binding-validation-result.md`](../slices/setup-binding/setup-binding-validation-result.md) | Historical setup-binding evidence. The active narrow route-local owner is [`setup-binding/README.md`](setup-binding/README.md). |
