# Discovery Tracks

## Status

Discovery-track navigation index.

This directory is a legacy path for discovery tracks. Tracks group discovery
work by durable user workflow, problem area, or authority boundary; they are
not active product routes, implementation owners, or workflow plans.

Use track indexes for discovery status and validation sequencing unless an
index is explicitly marked retired; use validation results for slice-local
evidence. Once a track has live engineering ownership, use
[`../../product/target-journeys.md`](../../product/target-journeys.md) for product
journey framing,
[`../../engineering/workflow-validation-map.md`](../../engineering/workflow-validation-map.md)
for use case validation sequencing, and
[`../../product/target-capabilities.md`](../../product/target-capabilities.md)
for capability maturity. Use
[`../../engineering/implementation-register.md`](../../engineering/implementation-register.md)
for live implementation ownership.

## Use Instead For Active Work

| Owner | Use For |
| --- | --- |
| [`../../product/adoption-strategy.md`](../../product/adoption-strategy.md) | Current product adoption paths. |
| [`../../product/target-journeys.md`](../../product/target-journeys.md) | Current target product journeys, primary workflows, and use cases to prove. |
| [`../../engineering/workflow-validation-map.md`](../../engineering/workflow-validation-map.md) | Current use case validation sequencing after discovery evidence moves toward implementation. |
| [`../../product/target-capabilities.md`](../../product/target-capabilities.md) | Current target product capabilities, maturity, evidence, and advancement questions. |
| [`../../brownfield/README.md`](../../brownfield/README.md) | Current-state, transition architecture, migration strategy, and migration roadmap for brownfield context. |
| [`../../engineering/implementation-register.md`](../../engineering/implementation-register.md) | Current live implementation owners. |

## Discovery Tracks

| Track | Use For |
| --- | --- |
| [`adoption-routes.md`](adoption-routes.md) | Historical discovery framing for evidence-backed adoption routes by durable user workflow. |
| [`measurement-records/README.md`](measurement-records/README.md) | Measurement records, import/source decisions, storage writing, selected handoff, package use, and source observation. |
| [`measurement-records/import-source-decision.md`](measurement-records/import-source-decision.md) | Current import/source discovery decisions, deferred decisions, reopen triggers, and next-slice guidance. |
| [`measurement-records/legacy-brownfield-adoption-decision.md`](measurement-records/legacy-brownfield-adoption-decision.md) | Current post-run-first legacy adoption discovery decisions, deferred decisions, reopen triggers, and stop rule. |
| [`measurement-context/README.md`](measurement-context/README.md) | Resolved measurement-record context-link comparison and remaining measurement-context support-family posture. |
| [`experiment-code/README.md`](experiment-code/README.md) | Experiment-code recording, managed code versions, workspace materialization, and prepared-run code context. |
| [`environment-operation/README.md`](environment-operation/README.md) | Environment declaration, file observation, review bundles, manager command intent, and external result recording. |
| [`parameter-state/README.md`](parameter-state/README.md) | Parameter-state management, adapter import review, storage read/write, selection context, and prepared-run review composition. |
| [`setup-binding/README.md`](setup-binding/README.md) | Setup-binding snapshots, generated line/readout views, measurement run-start setup-context references, and binding-change attention. |
| [`calibration-continuation/README.md`](calibration-continuation/README.md) | Calibration continuation, reviewable step state, accepted write handoff, and calibration-derived parameter-state measurement context. |
| [`calibration-continuation/decision.md`](calibration-continuation/decision.md) | Current calibration continuation discovery decision, deferred decisions, reopen triggers, and stop rule. |
| [`selected-reference/README.md`](selected-reference/README.md) | Selected-reference context comparison, recorded-code comparison, and objective comparison findings. |

## Retired Discovery Notes

| Note | Use For |
| --- | --- |
| [`../archive/measurement-records-handoff-route/README.md`](../archive/measurement-records-handoff-route/README.md) | Retired handoff package route map and historical discovery synthesis; current handoff boundaries live in engineering prototype-boundary and module docs. |
| [`../archive/measurement-records-handoff-route/decision.md`](../archive/measurement-records-handoff-route/decision.md) | Retired handoff route decision closeout; preserved for historical deferrals, reopen triggers, and stop-rule context. |

## Related Non-Route Owners

| Owner | Use For |
| --- | --- |
| [`../problem-briefs/README.md`](../problem-briefs/README.md) | Evidence-backed problem framing before choosing a validation question. |
| [`README.md`](../archive/slice-inventory.md) | How to use discovery slice results as evidence. |
| [`slice-inventory.md`](../archive/slice-inventory.md) | Historical flat discovery slice inventory. |
| [`../synthesis/measurement-context-backlog.md`](../synthesis/measurement-context-backlog.md) | Shared backlog for measurement-context-shaped validation work across routes. |
| [`../problem-briefs/setup-binding.md`](../problem-briefs/setup-binding.md) and [`setup-binding-validation-result.md`](../archive/slice-inventory.md) | Historical setup-binding evidence. The active narrow route-local owner is [`setup-binding/README.md`](setup-binding/README.md). |
