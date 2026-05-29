# Calibration Fit Continuation Composition Validation Plan

## Status

Validation-planning draft.

This is not an ADR, final workflow model, fitting framework, score contract,
analysis-result model, dataset registry, replay harness, GUI design, runner
design, retry policy, write-back policy, remote-execution design, or
hardware-control decision. It defines a narrow composition question between the
calibration work continuation and fit validation dataset slices.

Related inputs:

- [`calibration-work-continuation-validation-result.md`](calibration-work-continuation-validation-result.md)
- [`calibration-fit-validation-dataset-validation-result.md`](calibration-fit-validation-dataset-validation-result.md)

Artifact posture: planned fixture inputs and expected outputs should be
`internal_validation_summary` repository-safe artifacts, not portable/public
export datasets. The slice should not produce a dataset package, handoff
artifact, or lab-sharing bundle.

## Validation Question

Can Scopecat connect a user-owned fit recovery to calibration continuation
while preserving the relevant failed/refit attempt history as lab-internal
validation context, without Scopecat executing fits, scoring results, choosing
ROI or initial guesses, replaying cases, applying writes, or controlling
hardware?

This slice should validate only composition continuity:

- the recovered fit incident is the one linked to the current calibration step;
- the validation case measurement is a measurement output of the linked current
  step;
- the chosen recovery action is user-declared and belongs to that incident;
- the downstream calibration step can proceed only when continuation state says
  it is pending, intervening steps are completed, and no linked attention
  remains;
- the validation dataset candidate keeps the user-selected failed/refit
  attempts together for later analysis, including the current accepted attempt.

## User Job

When a calibration fit fails, the user's first job is usually to keep the
experiment moving. If there is clearly no signal, the likely action is to
adjust parameters and remeasure. If there is visible signal but fitting fails,
the user may adjust ROI or initial guess, refit, accept after review, and
select the failed and adjusted attempts for a validation dataset.

The user needs Scopecat to keep that experience continuous:

- show that the current calibration step recovered after user review;
- show the next calibration step that can continue;
- preserve the original failed fit and adjusted refit together;
- avoid requiring the user to later reconstruct which case should enter the
  validation set;
- keep fit execution, scoring, and fit-code improvement user-owned.

## First Fixture Concept

Start with one synthetic public-safe fixture that embeds the two existing child
inputs:

- a calibration continuation input where a Rabi amplitude step completed after
  a user-accepted adjusted refit and the next T1 step is pending;
- a fit validation dataset input where the same Rabi incident preserves both
  the failed default fit and the accepted adjusted refit;
- explicit composition links for current step, next step, fit incident,
  chosen recovery action, validation case, and selected attempt ids.

The fixture should be hand-authored and repository-safe. It should not include
real raw data, real paths, real hostnames, real sample labels, private
identifiers, or sensitive lab values. It should not run fitting code, read
source files, inspect notebooks, call hardware, mutate parameter state, or
materialize a dataset registry entry.

## Candidate Summary Shape

If the fixture earns a code-shaped experiment, the first candidate should be a
side-effect-free composition over existing read models:

```text
FitContinuationCompositionInput
  -> build_calibration_continuation_summary(...)
  -> build_fit_validation_dataset_summary(...)
  -> build_fit_continuation_composition_summary(...)
```

The summary may include:

- `recovery`: the linked fit incident and chosen user-declared recovery action;
- `continuation_effect`: current-step and next-step lifecycle state plus
  whether continuation can proceed;
- `validation_preservation`: dataset draft posture, validation case, selected
  measurement reference, current-step output reference, fit-incident measurement
  reference, and selected failed/refit attempts;
- `linked_summary_ids`: child summary identities used only for traceability;
- `attention`: unresolved continuation or validation-readiness findings;
- `boundary`: summary posture and explicit non-claims.

The candidate should validate referential integrity across the child summaries
rather than inventing new workflow facts.

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
expectations may appear only as user-owned or fixture-declared facts inherited
from the child fit validation input.

## Done For This Planning Stage

This plan is sufficient when the next task can be stated as:

- create one small composition fixture;
- define an expected summary with recovery, continuation effect, validation
  preservation, links, attention, and boundary;
- prove the composition rejects broken step, incident, recovery, validation
  case, measurement-provenance, skipped-step, and selected-attempt links;
- prove continuation can proceed only when linked continuation and validation
  readiness allow it;
- keep fitting, scoring, replay, registry, GUI, write-back, and hardware
  behavior out of scope.
