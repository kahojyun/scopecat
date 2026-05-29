# Calibration Fit Recovery Review State Validation Result

## Status

Fixture validation result with tiny review-state candidate.

This is not an ADR, final GUI design, notebook integration, fitting framework,
score contract, analysis-result model, dataset registry, replay harness,
package/export format, runner design, retry policy, write-back policy,
remote-execution design, or hardware-control decision. It records what the
current fit recovery review-state fixture proved and where the boundary should
remain narrow.

Artifact posture: `internal_validation_summary`. The fixture and expected
output are repository-safe validation artifacts, not portable/public export
datasets, GUI artifacts, replay inputs, registry records, or lab-sharing
bundles.

## Inputs

- [`calibration-fit-recovery-review-state-validation-plan.md`](calibration-fit-recovery-review-state-validation-plan.md)
- [`calibration-fit-recovery-workflow-validation-result.md`](calibration-fit-recovery-workflow-validation-result.md)
- `tests/fixtures/calibration_fit_recovery_review_state/no_signal_and_visible_refit_review/`
- `implementation_candidates/calibration_fit_recovery_review_state/`

## Validated Boundary

The fixture validates a narrow review-state boundary: an explicit fit recovery
workflow can be projected into local review surface state without accepting GUI
implementation, fit execution, scoring, replay, registry, write-back, or
hardware-control behavior.

The current fixture reuses the recovery workflow pressure from two synthetic
incidents:

- no clear signal in a readout response scan, where the user chooses parameter
  adjustment and remeasurement and the dataset-selection control is disabled;
- visible-signal Rabi fitting failure, where the user accepts an adjusted ROI
  and initial-guess refit, can continue, and selects the failed/default plus
  accepted/adjusted attempts for lab-internal validation.

The expected summary organizes that context into:

- incident cards;
- primary selected actions;
- dataset-selection controls;
- continuation banner state;
- an empty `missing_context` list for the complete main fixture;
- carried child workflow attention;
- explicit boundary non-claims.

## Important Separations

The fixture clarified several boundaries that should be preserved:

- Review state is a local projection, not a GUI or notebook integration.
- Primary actions are fixture-declared user choices. Scopecat labels and
  surfaces them but does not choose one.
- The disabled no-signal dataset control is review-state presentation of the
  workflow boundary, not a dataset policy engine.
- The continuation banner summarizes readiness. It does not schedule,
  execute, remeasure, or write parameters.
- Missing replay context is carried as attention. It is not a replay harness,
  runner request, or fit-code invocation.
- Dataset selection remains lab-internal validation state, not a portable
  package, public export, registry entry, or sharing bundle.

## Review-State Candidate

The tiny implementation candidate checks that the current read model can be
produced mechanically from explicit fixture facts and the child recovery
workflow summary.

It assembles and validates:

- child workflow recovery, continuation, and dataset-offer records by
  incident id;
- fixture-selected incident id membership;
- recovery action continuity between input and child workflow summary;
- dataset selected-state continuity between input and child workflow summary;
- card severity derived from child continuation and dataset selection;
- action labels for known user-declared recovery actions;
- no-signal dataset-selection controls disabled before remeasurement;
- continuation banner state from blocking and ready child readiness records;
- selected-case missing replay context copied into `missing_context` when child
  workflow attention reports it;
- child workflow attention carried through unchanged.

The builder remains side-effect free. It does not render a GUI, execute fitting
code, read source data, select ROIs, generate initial guesses, run notebooks,
replay validation cases, remeasure, apply parameter writes, schedule work,
materialize a dataset registry, or control hardware.

## What The Fixture Can Answer

The current summary can answer:

- which incidents would appear as review cards;
- which incident is blocking continuation because the user needs
  remeasurement;
- which incident can continue after an accepted visible-signal refit;
- which user-declared action is selected for each incident;
- which dataset-selection control is disabled or enabled;
- which validation case preserves the failed/refit attempt pair;
- that the main fixture's selected case has no missing user-owned replay
  context;
- that the projection remains an internal validation summary rather than an
  export, registry, replay, fitting, or GUI contract.

## Still Not Earned

This validation does not earn:

- GUI implementation;
- notebook integration;
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
- hardware control.

## Remaining Risks

- The fixture is hand-authored and synthetic. It validates shape and boundary,
  not product usefulness.
- The projection covers one no-signal case and one visible-signal accepted
  refit. It does not cover ambiguous signal, many targets, skipped targets,
  conflicting user choices, partial validation context, or dataset versioning.
- The summary does not prove that a real GUI or notebook-side interaction would
  feel continuous enough for users.
- Replay remains future user-owned intent. No harness, adapter, or fit-code
  invocation shape has been validated.

## Slice Recommendation

This slice is enough to keep the recovery review state as a read-model
candidate. The next useful validation should pressure one of two adjacent
areas: recording the user's interaction sequence around action/dataset
selection, or defining a minimal user-owned replay/fit-code handoff shape for
selected validation cases.

Do not start a dataset registry, fitting API, automatic ROI or initial-guess
selection, parameter write-back, or hardware-control work from this slice.
