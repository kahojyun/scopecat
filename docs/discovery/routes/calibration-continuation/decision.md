# Calibration Continuation Route Decision Consolidation

## Status

Discovery decision consolidation, not an ADR.

This note closes the current calibration continuation discovery pass as a
coherent route backbone. It records what the validated slices now support and
where future work should wait for real workflow pressure. It does not accept a
final workflow schema, relation graph, GUI, runner, scheduler, fitting
framework, hardware-control contract, storage architecture, or shared
calibration/measurement/parameter-state domain model.

## Accepted For Now

The validated calibration continuation route is a **reviewable local workflow**
that can connect calibration evidence to later measurement context without
turning Scopecat into a calibration executor:

```text
calibration step intent
  -> resolved step record
  -> measurement observation link
  -> declared fit-result reference
  -> proposed parameter write
  -> accepted write handoff
  -> parameter-state intake/storage
  -> prepared-run selected parameter context
  -> measurement-record run-start context link
```

Calibration owns reviewable step state, observation links, fit-result
references, proposed writes, missing-evidence findings, timeline review, local
review cards, and user-declared review action records.

Parameter-state management owns accepted handoff intake, managed snapshot
creation, storage, read views, and later prepared-run parameter-context
selection. Calibration evidence remains provenance for the managed
parameter-state snapshot. The managed parameter-state snapshot is the
canonical parameter context for later prepared runs and measurement records
when users have adopted Scopecat parameter-state management.

An external apply decision is separate. It records that a user intends to apply
or has applied a proposed calibration change outside Scopecat, such as by
editing an existing parameter file or using a lab-owned tool. External apply
does not create managed parameter context, does not prove hardware state, and
does not replace parameter-state handoff. Any external files or receipts from
that path remain supporting evidence unless a later adapter/import route maps
them into managed parameter state.

Measurement records can link the selected parameter-state snapshot as
optional reference-only run-start context. Missing or mismatched measurement
context is review evidence; it does not invalidate primary measurement data by
default.

The current notebook/CLI posture is summary-first and read-only. The route can
project review-state cards, backbone context, backbone findings, and
labels-only action choices into local review data without defining a GUI,
executing notebook cells, or executing actions.

User review choices can be recorded against labels exposed by the review
surface. Recording a choice is audit/review intent only. It does not repair
context, rerun fitting, write parameters, apply hardware state, start a run, or
advance workflow state automatically.

## Current Track Map

| Track | Current slices | Earned responsibility |
| --- | --- | --- |
| Continuation state | Calibration work continuation | Assemble planned steps, observed outputs, review gates, proposed writes, blocked steps, and interventions without scheduler or executor ownership. |
| Step and observation continuity | Step intent resolution, step observation link | Freeze moving intent selectors into step records and link measurement records as observed outputs without payload reads or shared relation graph behavior. |
| Fit/write review chain | Fit result link, proposed write link, accepted write handoff | Preserve observation, measurement, fit-result, proposed-write, base parameter-state, external-apply decisions, and accepted handoff continuity without fitting, write-back, rollback, hardware control, or treating external apply as managed state. |
| Review completeness | Review bundle, missing evidence findings, timeline trace, review state projection | Surface missing evidence, ordering/timestamp issues, and per-step review cards without executing actions or starting parameter-state intake. |
| Parameter-state bridge | Calibration parameter-state intake/storage, source-agnostic prepared-run consumption/review chain | Let accepted calibration writes become managed parameter-state snapshots and later prepared-run parameter context through parameter-state-owned boundaries. |
| Measurement context backbone | Calibration-derived parameter-state measurement context, backbone context findings | Prove happy-path continuity into later measurement context and surface missing/partial context as review findings. |
| Local review consumption | Calibration continuation review surface, review action recording | Show review cards, backbone context, findings, and labels-only actions in notebook/CLI-shaped data, then record explicit user choices without executing them. |

## Boundary Decisions

Keep these boundaries explicit:

- Calibration step records are retrospective snapshots. Moving intent remains
  separate from resolved step records.
- Measurement observations are reference-only links unless another route
  explicitly validates payload reads.
- Fit results are declared external summaries. The route does not execute,
  score, select models, choose ROIs, or infer scientific validity.
- Proposed writes and accepted parameter-state handoffs remain `not_applied`
  until a separate hardware/write-back authority exists. External apply is an
  explicitly outside-Scopecat decision path; it can be recorded for review, but
  it does not create managed parameter state or prove current instrument state.
- Compatibility outputs are not canonical context. The managed
  parameter-state snapshot is the parameter context; derivative files are
  optional supporting evidence if another artifact route needs them.
- Review-state and review-surface actions are labels. Recording a user choice
  is not action execution.
- GUI behavior, scheduler behavior, runner behavior, and workflow automation
  remain deferred.

## Deferred Decisions

Keep these out of the current route until a named workflow requires them:

- final calibration workflow DAG, scheduler, retry policy, or continuation
  engine;
- live executor or runner integration;
- GUI component model, interaction design, routing, or production rendering;
- notebook execution integration;
- measurement payload reading, fitting execution, model selection, scoring,
  ROI/outlier selection, or scientific validity decisions;
- hardware apply, hardware control, current instrument state, rollback, or
  write-back authority;
- durable relation graph traversal or repair;
- shared calibration, measurement, prepared-run, or parameter-state schema;
- public/export review packages or lab-sharing artifacts for calibration
  continuation state.

## Reopen Triggers

Do more calibration continuation discovery only when one of these concrete
triggers appears:

- Real notebook/CLI workflows show that the review-surface or recorded-action
  labels do not match how users actually continue calibration work.
- Users need Scopecat to execute a specific action currently represented only
  as a label, such as rerun measurement, record fit outcome, prepare handoff,
  or apply a parameter write.
- Users need payload-aware review, fitting, scoring, or plot inspection inside
  the calibration route rather than via declared external summaries.
- Hardware/write-back ownership becomes necessary, including current
  instrument-state recording, apply receipts, rollback, or safety review.
- A GUI prototype needs concrete component behavior beyond the current
  notebook/CLI-shaped review surface.
- Multiple routes need the same lifecycle and failure semantics for review
  actions, relation facts, or context findings; then reconsider shared model
  extraction with a narrow accepted decision.

## Stop Rule

Do not add more calibration continuation slices merely to restate the current
backbone, optional measurement context, labels-only action posture, or
no-execution/no-hardware boundary. Future work should name the missing user
workflow and the authority boundary it changes.
