# Calibration Continuation Engineering Prototype Promotion Decision

## Status

Accepted narrow promotion.

## Decision

Promote the validated calibration continuation review-surface and
review-action recording slices into a route-local engineering prototype under
`scopecat.calibration_continuation`.

The promoted surface is intentionally narrow:

- local notebook/CLI-shaped review surface over prior declared calibration
  review-state, backbone context, and backbone finding summaries;
- route header, step review lane, backbone context panel, backbone findings
  panel, labels-only action palette, and attention projection;
- review-only recording of explicit user choices against exposed action
  labels.

The accepted chain is:

```text
declared calibration review-state summary
  -> declared calibration-derived parameter-state backbone context
  -> declared backbone context findings
  -> local review surface
  -> labels-only action palette
  -> review-only action recording
```

This promotion intentionally keeps calibration continuation as a reviewable
local workflow. It does not promote fitting, calibration execution, notebook
execution, scheduler or runner behavior, GUI component behavior, measurement
payload reads, parameter write-back, hardware apply/control, automatic run
start, storage mutation, relation-graph traversal, or shared calibration,
measurement, prepared-run, or parameter-state schemas.

## Boundary

The promoted outputs are local `review_summary` / local review projections.
They are not portable/public/export artifacts.

Repository fixtures remain repository-safe validation fixtures. Runtime
redaction is not added at this boundary because the promoted surfaces do not
produce portable handoff, package, or public documentation artifacts.

Review-surface action labels are not commands. Recording a user choice against
one of those labels is audit/review intent only and does not execute, repair,
advance, retry, apply, or mutate workflow state.

## Rationale

The calibration continuation route decision closes the current discovery pass
around a stable reviewable backbone:

```text
calibration observation
  -> accepted write handoff
  -> parameter-state intake/storage
  -> prepared-run selected parameter context
  -> measurement-record run-start context link
```

The route does not need more discovery slices merely to restate the same
backbone or no-execution/no-hardware posture. The useful implementation step is
a small local consumption surface that downstream notebook, CLI, or future GUI
work can consume without granting action authority.

## Engineering Coverage

| Discovery slice group | Engineering coverage | Current owner |
| --- | --- | --- |
| Calibration continuation review surface | Promoted into route-local engineering code with typed request/result objects and raw-dictionary adapters only at the fixture/current-caller edge. | [`scopecat/calibration_continuation/README.md`](../../../scopecat/calibration_continuation/README.md), this decision |
| Calibration review action recording | Promoted as review-only event recording against review-surface labels. Events remain audit intent and do not execute labels. | [`scopecat/calibration_continuation/README.md`](../../../scopecat/calibration_continuation/README.md), this decision |
| Step intent resolution, observation links, fit-result links, proposed-write links, accepted-write handoff, missing-evidence findings, timeline trace, review state projection, and calibration-derived parameter-state context | Historical validation evidence consumed as prior declared summaries. Their live producers are not promoted in this module. | Discovery validation results and future narrower decisions if reopened. |
| Parameter-state intake/storage and prepared-run parameter-state consumption | Owned by the parameter-state route. Calibration continuation consumes only declared summary facts and does not reach into parameter-state storage internals. | [`../parameter-state/engineering-prototype-promotion-decision.md`](../parameter-state/engineering-prototype-promotion-decision.md) |

## Next Decision Gate

Do not continue by promoting the whole calibration continuation route. Future
work should choose one explicit authority change:

- GUI component integration over the accepted review surface;
- notebook/CLI practice review that changes action labels or review-state
  shape;
- payload-aware calibration review, fitting, or plotting;
- execution/runner/scheduler behavior for a named action;
- hardware apply/write-back authority and safety review;
- producer-side live implementations for selected historical child summaries.

Each path needs its own non-claims before it can add action execution,
hardware control, parameter write-back, automatic run start, or shared schemas.
