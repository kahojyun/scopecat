# Calibration Continuation Route

## Status

Discovery route index with an accepted narrow engineering prototype owner.

This route groups the validated calibration continuation slices and names the
current calibration-to-measurement backbone. The narrow review-surface and
review-action recording boundary is now promoted under
[`../../../architecture/calibration-continuation/engineering-prototype-promotion-decision.md`](../../../architecture/calibration-continuation/engineering-prototype-promotion-decision.md)
and [`../../../../scopecat/calibration_continuation/README.md`](../../../../scopecat/calibration_continuation/README.md).
The route still does not accept a final workflow schema, relation graph, GUI,
runner, scheduler, fitting framework, hardware-control contract, or shared
measurement/parameter-state model.

Current route closeout:
[`decision.md`](decision.md).

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
| Notebook/CLI consumption can show review cards and backbone findings together. | [`../../slices/calibration/calibration-continuation-review-surface-validation-result.md`](../../slices/calibration/calibration-continuation-review-surface-validation-result.md) |
| Explicit user choices can be recorded against review-surface labels. | [`../../slices/calibration/calibration-review-action-recording-validation-result.md`](../../slices/calibration/calibration-review-action-recording-validation-result.md) |

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

The current discovery backbone has a narrow local review-surface owner. Prefer
new slices only when they answer a concrete workflow question that changes an
authority boundary. High-value follow-ups are:

- compare recorded review choices against real notebook/CLI review practices
  before adding GUI behavior, execution behavior, or shared route schemas.
