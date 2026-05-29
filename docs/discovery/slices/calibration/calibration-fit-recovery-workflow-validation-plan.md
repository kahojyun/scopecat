# Calibration Fit Recovery Workflow Validation Plan

## Status

Validation-planning draft.

This is not an ADR, final workflow model, fitting framework, score contract,
analysis-result model, dataset registry, replay harness, GUI design, runner
design, retry policy, write-back policy, remote-execution design, or
hardware-control decision. It defines a narrow validation question for the user
workflow immediately after calibration fit trouble.

Related inputs:

- [`calibration-fit-validation-dataset-validation-result.md`](calibration-fit-validation-dataset-validation-result.md)
- [`calibration-fit-continuation-composition-validation-result.md`](calibration-fit-continuation-composition-validation-result.md)

Artifact posture: planned fixture inputs and expected outputs should be
`internal_validation_summary` repository-safe artifacts, not portable/public
export datasets. The slice should not produce a dataset package, handoff
artifact, or lab-sharing bundle.

## Validation Question

Can Scopecat represent the user's immediate recovery workflow after fit trouble
so the user can distinguish no-signal remeasurement from visible-signal refit
recovery, continue calibration when appropriate, and preserve selected
failed/refit attempts for later lab-internal validation, without Scopecat
executing fits, scoring results, choosing ROI or initial guesses, replaying
cases, applying writes, or controlling hardware?

This slice should validate only recovery workflow continuity:

- no clear signal is withheld from validation and points to parameter
  adjustment plus remeasurement;
- visible signal with failed fitting can preserve the failed default attempt
  and accepted adjusted refit together;
- accept-after-refit continuation requires visible signal and an accepted
  current fit attempt;
- continuation readiness stays explicit and user-owned;
- dataset selection remains lab-internal validation context, not a registry or
  replay harness.

## User Job

When a fit fails, the user's first job is to keep the experiment moving.

The user needs Scopecat to help record:

- whether the data appears to have no clear signal or visible signal;
- which immediate recovery action the user chose;
- whether continuation is blocked by remeasurement, blocked by refit/review, or
  ready to proceed after acceptance;
- whether the case should be withheld or selected for validation;
- which failed and adjusted attempts explain the selected validation case.

## First Fixture Concept

Start with one synthetic public-safe fixture with two incidents:

- a no-signal readout/resonator case where the user chooses parameter
  adjustment and remeasurement, and the case is withheld from the validation
  dataset;
- a visible-signal Rabi fit failure where the user adjusts ROI and initial
  guess, accepts the refit, can continue, and selects both the failed default
  attempt and adjusted accepted refit for validation.

The fixture should be hand-authored and repository-safe. It should not include
real raw data, real paths, real hostnames, real sample labels, private
identifiers, or sensitive lab values. It should not run fitting code, read
source files, inspect notebooks, call hardware, mutate parameter state, or
materialize a dataset registry entry.

## Candidate Summary Shape

If the fixture earns a code-shaped experiment, the first candidate should be a
side-effect-free projection:

```text
FitRecoveryWorkflowInput
  -> build_fit_recovery_workflow_summary(...)
  -> FitRecoveryWorkflowSummary
```

The summary may include:

- `immediate_recovery`: user-declared recovery action, signal classification,
  action family, available actions, and measurement reference;
- `continuation_readiness`: whether the linked step can continue, requires
  remeasurement, requires refit, or requires review;
- `dataset_selection_offers`: selected or withheld state, selected fit attempt
  refs, selected attempt summaries, validation case id, and replay expectation;
- `dataset_draft`: lab-internal dataset draft posture, selected cases, withheld
  incidents, and readiness;
- `attention`: selected cases missing replay context, non-lab-internal posture,
  or no-signal cases selected before remeasurement review;
- `boundary`: summary posture and explicit non-claims.

## Boundary

Do not include these in the first slice:

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
- portable/public dataset package;
- GUI implementation.

Fit attempts, scores, thresholds, ROI edits, initial guesses, and replay
expectations may appear only as user-owned or fixture-declared facts.

## Done For This Planning Stage

This plan is sufficient when the next task can be stated as:

- create one small recovery workflow fixture;
- define expected summary output with immediate recovery, continuation
  readiness, dataset-selection offers, dataset draft, attention, and boundary;
- prove no-signal and visible-signal cases are separated;
- prove selected visible-signal cases carry paired failed/refit attempts,
  including at least one failed prior attempt and the accepted current attempt;
- keep fitting, scoring, replay, registry, GUI, write-back, and hardware
  behavior out of scope.
