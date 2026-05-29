# Calibration Fit Continuation Composition Validation Result

## Status

Fixture validation result with tiny composition candidate.

This is not an ADR, final workflow model, fitting framework, score contract,
analysis-result model, dataset registry, replay harness, package/export
format, GUI design, runner design, retry policy, write-back policy,
remote-execution design, or hardware-control decision. It records what the
current fit-continuation composition fixture proved and where the boundary
should remain narrow.

Artifact posture: `internal_validation_summary`. The fixture and expected
output are repository-safe validation artifacts, not portable/public export
datasets.

## Inputs

- [`calibration-fit-continuation-composition-validation-plan.md`](calibration-fit-continuation-composition-validation-plan.md)
- [`calibration-work-continuation-validation-result.md`](calibration-work-continuation-validation-result.md)
- [`calibration-fit-validation-dataset-validation-result.md`](calibration-fit-validation-dataset-validation-result.md)
- `tests/fixtures/calibration_fit_continuation_composition/rabi_recovery_with_validation/`
- `implementation_candidates/calibration_fit_continuation_composition/`

## Validated Boundary

The fixture validates a narrow composition boundary: a user-owned fit recovery
can be linked to both calibration continuation and validation dataset curation
without accepting fit execution, scoring, replay, registry, write-back, GUI, or
hardware-control behavior.

The current fixture represents one synthetic Rabi recovery:

- the resonator check step completed;
- the Rabi amplitude step completed after the user accepted an adjusted refit;
- the next T1 step is pending;
- the fit validation dataset draft selects both the failed default fit attempt
  and the adjusted accepted refit attempt.

The expected summary organizes that context into:

- linked recovery action for the fit incident;
- continuation effect for the current and next calibration steps;
- selected validation case, current-step output reference, fit-incident
  measurement reference, and selected attempt preservation;
- linked child summary identities;
- attention findings when continuation or validation readiness is not clean;
- explicit boundary non-claims.

## Important Separations

The fixture clarified several boundaries that should be preserved:

- Composition links existing read summaries; it does not execute either child
  workflow.
- A recovery action remains a user-declared choice. Scopecat validates that the
  chosen action belongs to the linked incident, but it does not choose the
  action.
- The current step can be treated as recovered only through the child
  continuation summary's lifecycle state, not through a fit-result schema.
- The selected validation case must derive from the linked incident and its
  measurement must be a measurement output of the linked current step.
- The downstream step can proceed only when the linked continuation state is
  pending, intervening steps are completed, and no linked attention remains.
- The failed default fit and adjusted accepted refit remain validation context,
  not a replay run or score contract.
- The dataset draft remains lab-internal validation state, not a portable
  package or registry entry.

## Composition Candidate

The tiny implementation candidate checks that the current read models can be
composed mechanically from explicit fixture facts.

It assembles and validates:

- linked current and next step ids against the continuation summary;
- linked fit incident ids against the fit validation queue;
- linked validation case ids against selected dataset candidates;
- linked recovery action ids against recovery actions;
- recovery action ownership by the linked incident;
- recovery action chosen state;
- validation-case ownership by the linked incident;
- validation-case measurement continuity through the linked incident and
  current step measurement output;
- selected attempt ids matching the validation case's selected attempt refs;
- selected attempt ids including the current fit attempt;
- no incomplete intermediate steps between the recovered current step and
  linked next step;
- continuation attention when the downstream step remains blocked;
- validation attention when the dataset draft is not ready for lab-internal
  validation.

The builder remains side-effect free. It does not execute fitting code, read
source data, select ROIs, generate initial guesses, run notebooks, replay
validation cases, remeasure, apply parameter writes, schedule work, or control
hardware.

## What The Fixture Can Answer

The current summary can answer:

- which recovered fit incident is linked to the continuation step;
- which user-declared recovery action was chosen;
- whether the linked next calibration step can continue;
- which validation dataset draft is preserving the case;
- which failed/refit attempts were selected as validation context;
- whether the composition is blocked by unresolved continuation or validation
  readiness findings;
- that the composition remains an internal validation summary rather than an
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
- The composition covers one recovered visible-signal Rabi case. It does not
  cover no-signal remeasurement, conflicting user decisions, multiple targets,
  skipped continuation, partial validation context, or dataset versioning.
- The summary does not prove that the user-facing workflow is ergonomic enough
  to replace manual notebook and file curation.
- Replay remains future user-owned intent. No harness, adapter, or fit-code
  invocation shape has been validated.

## Slice Recommendation

This slice is enough to keep exploring the workflow at the read-model level.
The next useful validation should be a user-facing workflow sketch or fixture
that distinguishes no-signal remeasurement from visible-signal refit recovery,
while still preserving selected failed/refit cases for later lab-internal
validation.

Do not start a dataset registry, replay harness, fitting API, automatic ROI or
initial-guess selection, parameter write-back, or hardware-control work from
this slice.
