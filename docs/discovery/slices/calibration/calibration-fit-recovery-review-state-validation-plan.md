# Calibration Fit Recovery Review State Validation Plan

## Status

Validation-planning draft.

This is not an ADR, final GUI design, notebook integration, fitting framework,
score contract, analysis-result model, dataset registry, replay harness,
package/export format, runner design, retry policy, write-back policy,
remote-execution design, or hardware-control decision. It defines a narrow
validation question for projecting fit recovery workflow state into a local
review surface shape.

Related inputs:

- [`calibration-fit-recovery-workflow-validation-result.md`](calibration-fit-recovery-workflow-validation-result.md)
- [`calibration-fit-validation-dataset-validation-result.md`](calibration-fit-validation-dataset-validation-result.md)
- [`calibration-fit-continuation-composition-validation-result.md`](calibration-fit-continuation-composition-validation-result.md)

Artifact posture: planned fixture inputs should be repository-safe synthetic
fixtures, and expected outputs should declare `internal_validation_summary`.
The slice should not produce a GUI artifact, dataset package, handoff artifact,
lab-sharing bundle, replay harness, or registry entry.

## Validation Question

Can Scopecat project the fit recovery workflow into review state that a future
notebook panel or GUI could consume, so the user can see incident cards,
primary recovery actions, dataset-selection controls, continuation readiness,
and missing-context findings without Scopecat implementing the GUI, running
fits, scoring results, choosing ROI or initial guesses, replaying cases,
applying writes, or controlling hardware?

This slice should validate only review-state projection:

- no-clear-signal cases surface as blocking remeasurement work;
- visible-signal accepted refit cases can surface as ready and optionally
  selected for lab-internal validation;
- dataset-selection controls expose fixture-declared selection state while
  disabling no-signal dataset selection before remeasurement;
- continuation banner state summarizes child workflow readiness;
- missing replay context remains an attention finding, not a replay harness.

## User Job

When a fit fails, the user's first job is to keep the experiment moving.

The user needs a compact local review state that helps them see:

- which incidents need parameter adjustment and remeasurement;
- which visible-signal incidents can continue after an accepted refit;
- which user-declared action is currently selected;
- which validation cases preserve the failed/refit attempt pair;
- whether missing notes or replay expectations make a selected case
  incomplete for later lab-internal review.

## First Fixture Concept

Start with one synthetic public-safe fixture that embeds the validated recovery
workflow input and adds only a local `review_surface` selection context:

- a no-signal readout/resonator case where the dataset-selection control is
  disabled and the continuation banner remains blocked;
- a visible-signal Rabi fit failure where the accepted adjusted refit can
  continue and the failed/default plus accepted/adjusted attempts are selected
  for validation.

The fixture should be hand-authored and repository-safe. It should not include
real raw data, real paths, real hostnames, real sample labels, private
identifiers, or sensitive lab values. It should not run fitting code, read
source files, inspect notebooks, call hardware, mutate parameter state,
materialize a dataset registry entry, render a GUI, or emit a portable
artifact.

## Candidate Summary Shape

If the fixture earns a code-shaped experiment, the first candidate should be a
side-effect-free projection over the recovery workflow candidate:

```text
FitRecoveryReviewStateInput
  -> build_fit_recovery_workflow_summary(...)
  -> build_fit_recovery_review_state_summary(...)
  -> FitRecoveryReviewStateSummary
```

The summary may include:

- `surface_context`: fixture-declared local review surface metadata;
- `workflow_summary_id`: identity of the child recovery workflow summary;
- `incident_cards`: review cards with signal classification, severity,
  continuation state, dataset state, measurement reference, and badges;
- `primary_actions`: selected user-declared recovery actions with labels and
  projected continuation/dataset effects;
- `dataset_selection_controls`: selected state, enabled state, selected
  attempts, validation case id, and disabled reason;
- `continuation_banner`: blocked and ready incident identifiers;
- `missing_context`: replay-context attention relevant to selected validation
  cases;
- `attention`: child workflow findings carried through unchanged;
- `boundary`: summary posture and explicit non-claims.

## Boundary

Do not include these in the first slice:

- GUI implementation;
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

Review cards, controls, and actions are local read-model state only. Fit
attempts, scores, thresholds, ROI edits, initial guesses, and replay
expectations may appear only as user-owned or fixture-declared facts.

## Done For This Planning Stage

This plan is sufficient when the next task can be stated as:

- create one small review-state fixture reusing the recovery workflow fixture;
- define expected summary output with cards, actions, controls, banner,
  missing context, attention, and boundary;
- prove no-signal and visible-signal cases remain separated in review state;
- prove selected visible-signal cases expose the paired failed/refit attempts;
- keep GUI, fitting, scoring, replay, registry, write-back, and hardware
  behavior out of scope.
