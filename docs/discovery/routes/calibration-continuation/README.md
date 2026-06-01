# Calibration Continuation Route

## Status

Provisional discovery route, not an ADR.

This route groups the validated calibration continuation slices and names the
current calibration-to-measurement backbone. It does not accept a final
workflow schema, relation graph, GUI, runner, scheduler, fitting framework,
hardware-control contract, or shared measurement/parameter-state model.

## Route Posture

Calibration continuation is currently validated as a reviewable local workflow:

- calibration steps can resolve moving intent into step-record snapshots;
- step records can link measurement records as observed outputs without
  reading payloads;
- fit-result references and proposed writes can be reviewed without executing
  fitting or writing parameters;
- accepted writes can be handed off to parameter-state management while
  remaining `not_applied`;
- parameter-state-owned intake and storage can turn an accepted calibration
  handoff into a managed parameter-state snapshot;
- a later prepared run can select that snapshot as required parameter context;
- the later measurement record can link the same snapshot as optional
  reference-only run-start context.

The validated backbone is:

```text
calibration observation
-> accepted write handoff
-> parameter-state intake/storage
-> prepared-run selected parameter context
-> measurement-record run-start context link
```

The old pause on a separate parameter-state thread is resolved for this
backbone. Future slices can treat the managed parameter-state snapshot as the
canonical parameter context while keeping calibration evidence as provenance.

## Current Backbone Evidence

| Step | Validated By |
| --- | --- |
| Calibration step links observed measurement records. | [`../../slices/calibration/calibration-step-observation-link-validation-result.md`](../../slices/calibration/calibration-step-observation-link-validation-result.md) |
| Fit/proposed-write review preserves measurement and parameter references. | [`../../slices/calibration/calibration-step-fit-result-link-validation-result.md`](../../slices/calibration/calibration-step-fit-result-link-validation-result.md), [`../../slices/calibration/calibration-step-proposed-write-link-validation-result.md`](../../slices/calibration/calibration-step-proposed-write-link-validation-result.md) |
| Accepted calibration write handoff stays review-only and `not_applied`. | [`../../slices/calibration/calibration-accepted-write-handoff-validation-result.md`](../../slices/calibration/calibration-accepted-write-handoff-validation-result.md) |
| Parameter-state intake/storage owns the managed snapshot. | [`../../slices/parameter-state/calibration-parameter-state-intake-validation-result.md`](../../slices/parameter-state/calibration-parameter-state-intake-validation-result.md), [`../../slices/parameter-state/calibration-parameter-state-storage-validation-result.md`](../../slices/parameter-state/calibration-parameter-state-storage-validation-result.md) |
| Prepared-run review can consume the calibration-derived state. | [`../../slices/parameter-state/prepared-run-source-agnostic-parameter-state-consumption-validation-result.md`](../../slices/parameter-state/prepared-run-source-agnostic-parameter-state-consumption-validation-result.md), [`../../slices/parameter-state/prepared-run-source-agnostic-parameter-state-review-chain-validation-result.md`](../../slices/parameter-state/prepared-run-source-agnostic-parameter-state-review-chain-validation-result.md) |
| The full backbone composes into later measurement context. | [`../../slices/calibration/calibration-derived-parameter-state-measurement-context-validation-result.md`](../../slices/calibration/calibration-derived-parameter-state-measurement-context-validation-result.md) |
| Missing or partial backbone context becomes review findings. | [`../../slices/calibration/calibration-backbone-context-findings-validation-result.md`](../../slices/calibration/calibration-backbone-context-findings-validation-result.md) |

## Boundary

This route still does not earn:

- measurement payload reads;
- fitting, calibration, measurement, or child-slice execution;
- automatic retry, remeasurement, continuation, or run start;
- hardware apply, hardware control, or current instrument state;
- parameter write-back;
- compatibility output as canonical context;
- durable relation-graph traversal;
- GUI workflow;
- shared calibration, measurement, prepared-run, or parameter-state schema.

## Next Useful Work

Prefer route-level or workflow-action slices only when they answer a concrete
user workflow question. High-value follow-ups are:

- record explicit user actions against review-state cards without executing
  those actions;
- consolidate how notebook/CLI surfaces consume the existing review-state and
  backbone summaries;
- pressure combined backbone findings with real notebook/CLI display needs
  before adding GUI behavior or shared route schemas.
