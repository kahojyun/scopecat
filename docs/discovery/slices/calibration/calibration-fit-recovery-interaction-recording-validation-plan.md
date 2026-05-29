# Calibration Fit Recovery Interaction Recording Validation Plan

## Status

Validation-planning draft.

This is not an ADR, final GUI design, notebook integration, fitting framework,
score contract, analysis-result model, dataset registry, replay harness,
package/export format, runner design, retry policy, write-back policy,
remote-execution design, or hardware-control decision. It defines a narrow
validation question for recording user-declared fit recovery interactions
before projecting the existing recovery workflow and review-state read models.

Related inputs:

- [`calibration-fit-recovery-workflow-validation-result.md`](calibration-fit-recovery-workflow-validation-result.md)
- [`calibration-fit-recovery-review-state-validation-result.md`](calibration-fit-recovery-review-state-validation-result.md)

Artifact posture: planned fixture inputs should be repository-safe synthetic
fixtures, and expected outputs should declare `internal_validation_summary`.
The slice should not produce a GUI artifact, notebook transcript, dataset
package, handoff artifact, lab-sharing bundle, replay harness, registry entry,
runner log, or fit result.

## Validation Question

Can Scopecat record explicit user fit-recovery interactions, apply them to a
known recovery workflow input, and project the resulting workflow/review state
without Scopecat implementing the interaction UI, running fits, scoring
results, choosing ROI or initial guesses, replaying cases, applying writes, or
controlling hardware?

This slice should validate only interaction recording continuity:

- user-declared signal classification can update an incident;
- user-declared recovery action can update the chosen action;
- user-owned review notes and replay expectations can be recorded as context;
- user-declared dataset selection can preserve visible-signal failed/refit
  attempt pairs;
- no-signal data cannot be recorded as a ready validation case before
  remeasurement;
- skipped targets remain informational rather than blocked continuation.

## User Job

When a fit fails, the user needs to get the experiment moving while preserving
enough context for later fit-code improvement.

The user needs Scopecat to help record:

- whether the data appears to have no clear signal or visible signal;
- the recovery action they chose;
- the note or replay expectation that explains the choice;
- whether the visible-signal failure/refit pair should become lab-internal
  validation context;
- which incident remains selected in the local review state.

## First Fixture Concept

Start with one synthetic public-safe fixture that contains unresolved
interaction state and a sequence of explicit user events:

- classify a readout incident as no clear signal;
- choose parameter adjustment and remeasurement for that incident;
- record a user note for the no-signal case;
- accept an adjusted visible-signal Rabi refit;
- record replay expectation context for the visible-signal case;
- select the visible-signal failed/refit attempts for lab-internal validation;
- select the visible incident in the local review surface.

The fixture should be hand-authored and repository-safe. It should not include
real raw data, real paths, real hostnames, real sample labels, private
identifiers, or sensitive lab values. It should not run fitting code, read
source files, inspect notebooks, call hardware, mutate parameter state,
materialize a dataset registry entry, render a GUI, or emit a portable
artifact.

## Candidate Summary Shape

If the fixture earns a code-shaped experiment, the first candidate should be a
side-effect-free projection:

```text
FitRecoveryInteractionRecordingInput
  -> apply fixture-declared interaction events
  -> build_fit_recovery_workflow_summary(...)
  -> build_fit_recovery_review_state_summary(...)
  -> FitRecoveryInteractionRecordingSummary
```

The summary may include:

- `recording_context`: fixture-declared local interaction context;
- `applied_events`: event ids, order, type, incident id, and authority;
- projected workflow and review-state summary ids;
- selected review incident id;
- `recorded_review_context`: compact proof that review-note and replay-context
  events were applied;
- `interaction_outcomes`: compact incident-level projection of signal
  classification, chosen action, continuation status, dataset control state,
  and review-card severity;
- `missing_context`: replay-context attention from the projected review state;
- `attention`: child workflow/review findings carried through unchanged;
- `boundary`: summary posture and explicit non-claims.

## Boundary

Do not include these in the first slice:

- GUI implementation;
- notebook integration;
- fitting implementation;
- fit model selection;
- Scopecat-defined score, pass/fail threshold, or scientific conclusion;
- automatic ROI selection, outlier rejection, or initial-guess generation;
- automatic remeasurement, retry, retune, or optimization;
- Scopecat-decided parameter write-back;
- hardware-control behavior;
- local executor or notebook execution;
- replay harness;
- dataset registry service;
- portable/public dataset package.

Interaction events are fixture-declared facts only. They are not proof of a GUI
event model, notebook command API, live interaction capture protocol, or final
workflow schema.

## Done For This Planning Stage

This plan is sufficient when the next task can be stated as:

- create one small interaction-recording fixture;
- define expected summary output with applied events, projected summary ids,
  recorded review context, outcomes, missing context, attention, and boundary;
- prove no-signal and visible-signal outcomes remain separated after applying
  events;
- prove visible-signal selected cases still require paired failed/refit
  context;
- keep GUI, notebook execution, fitting, scoring, replay, registry,
  write-back, and hardware behavior out of scope.
