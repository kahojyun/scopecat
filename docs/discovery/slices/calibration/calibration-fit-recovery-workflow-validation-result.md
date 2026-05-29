# Calibration Fit Recovery Workflow Validation Result

## Status

Fixture validation result with tiny workflow candidate.

This is not an ADR, final workflow model, fitting framework, score contract,
analysis-result model, dataset registry, replay harness, package/export
format, GUI design, runner design, retry policy, write-back policy,
remote-execution design, or hardware-control decision. It records what the
current fit recovery workflow fixture proved and where the boundary should
remain narrow.

Artifact posture: `internal_validation_summary`. The fixture and expected
output are repository-safe validation artifacts, not portable/public export
datasets.

## Inputs

- [`calibration-fit-recovery-workflow-validation-plan.md`](calibration-fit-recovery-workflow-validation-plan.md)
- [`calibration-fit-validation-dataset-validation-result.md`](calibration-fit-validation-dataset-validation-result.md)
- [`calibration-fit-continuation-composition-validation-result.md`](calibration-fit-continuation-composition-validation-result.md)
- `tests/fixtures/calibration_fit_recovery_workflow/no_signal_and_visible_refit/`
- `implementation_candidates/calibration_fit_recovery_workflow/`

## Validated Boundary

The fixture validates a narrow recovery workflow boundary: user-declared fit
trouble can be summarized into immediate recovery, continuation readiness, and
dataset-selection offers without accepting fit execution, scoring, replay,
registry, write-back, GUI, or hardware-control behavior.

The current fixture represents two synthetic recovery incidents:

- no clear signal in a readout response scan, where the user chooses parameter
  adjustment and remeasurement and withholds the case from validation;
- visible-signal Rabi fitting failure, where the user accepts an adjusted ROI
  and initial-guess refit and selects both failed/default and accepted/adjusted
  attempts for lab-internal validation.

The expected summary organizes that context into:

- immediate recovery actions;
- continuation readiness;
- dataset-selection offers;
- lab-internal dataset draft readiness;
- attention findings for invalid or incomplete selected cases;
- explicit boundary non-claims.

## Important Separations

The fixture clarified several boundaries that should be preserved:

- No-signal recovery is ordinary remeasurement pressure, not automatically a
  validation dataset case.
- Visible-signal fit failure can be valuable validation context when the failed
  attempt and accepted adjusted refit remain paired.
- Accept-after-refit continuation requires visible signal and an accepted
  current fit attempt.
- Recovery actions are user-declared choices. Scopecat records them but does
  not choose one.
- Continuation readiness is a review summary, not a scheduler or executor
  plan.
- Dataset selection remains lab-internal validation state, not a replay run,
  public export package, or registry entry.

## Workflow Candidate

The tiny implementation candidate checks that the current read model can be
produced mechanically from explicit fixture facts.

It assembles and validates:

- unique incident identifiers;
- chosen recovery action membership in available actions;
- fit attempt history references;
- non-empty selected-attempt lists for selected history-backed cases;
- explicit fit attempt history for selected validation cases;
- no-signal recovery choosing remeasurement rather than accepted refit;
- accepted refit recovery requiring visible signal and an accepted current
  attempt;
- current accepted attempt inclusion when a visible-signal refit is selected;
- failed prior attempt inclusion when a visible-signal refit is selected;
- no selected attempts on unselected incidents;
- no-signal selected-before-remeasurement attention;
- missing replay-context attention for selected cases;
- dataset draft readiness only inside the lab-internal posture.

The builder remains side-effect free. It does not execute fitting code, read
source data, select ROIs, generate initial guesses, run notebooks, replay
validation cases, remeasure, apply parameter writes, schedule work, or control
hardware.

## What The Fixture Can Answer

The current summary can answer:

- which recovery action the user chose for each incident;
- which incident requires remeasurement because there is no clear signal;
- which incident can continue after an accepted visible-signal refit;
- which validation case preserves the failed/refit pair;
- which incidents are withheld from the dataset draft;
- whether selected cases are missing replay context;
- that the workflow remains an internal validation summary rather than an
  export, registry, replay, fitting, or GUI contract.

## Still Not Earned

This validation does not earn:

- fitting implementation;
- fit model selection;
- Scopecat-defined score, pass/fail threshold, or scientific conclusion;
- automatic ROI selection, outlier rejection, or initial-guess generation;
- automatic remeasurement, retry, retune, or optimization;
- Scopecat-decided parameter write-back;
- local executor or notebook execution;
- replay harness;
- dataset registry service;
- portable/public dataset package;
- GUI implementation;
- hardware control.

## Remaining Risks

- The fixture is hand-authored and synthetic. It validates shape and boundary,
  not product usefulness.
- The workflow covers one no-signal case and one visible-signal accepted refit.
  It does not cover ambiguous signal, many targets, conflicting user choices,
  skipped targets, partial validation context, or dataset versioning.
- The summary does not prove that a GUI or notebook-side interaction would feel
  continuous enough for users.
- Replay remains future user-owned intent. No harness, adapter, or fit-code
  invocation shape has been validated.

## Slice Recommendation

This slice is enough to keep the recovery workflow as a read-model candidate.
The next useful validation should either pressure user interaction around
recording the recovery choice or connect this workflow to a future local review
surface. Do not start a dataset registry, replay harness, fitting API,
automatic ROI or initial-guess selection, parameter write-back, or
hardware-control work from this slice.
