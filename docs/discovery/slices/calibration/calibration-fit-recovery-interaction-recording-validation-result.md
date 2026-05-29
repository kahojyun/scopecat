# Calibration Fit Recovery Interaction Recording Validation Result

## Status

Fixture validation result with tiny interaction-recording candidate.

This is not an ADR, final GUI design, notebook integration, fitting framework,
score contract, analysis-result model, dataset registry, replay harness,
package/export format, runner design, retry policy, write-back policy,
remote-execution design, or hardware-control decision. It records what the
current fit recovery interaction-recording fixture proved and where the
boundary should remain narrow.

Artifact posture: fixture inputs are repository-safe synthetic fixtures, and
expected/candidate outputs declare `internal_validation_summary`. They are not
portable/public export datasets, GUI artifacts, notebook transcripts, replay
inputs, registry records, fit results, runner logs, or lab-sharing bundles.

## Inputs

- [`calibration-fit-recovery-interaction-recording-validation-plan.md`](calibration-fit-recovery-interaction-recording-validation-plan.md)
- [`calibration-fit-recovery-workflow-validation-result.md`](calibration-fit-recovery-workflow-validation-result.md)
- [`calibration-fit-recovery-review-state-validation-result.md`](calibration-fit-recovery-review-state-validation-result.md)
- `tests/fixtures/calibration_fit_recovery_interaction_recording/no_signal_and_visible_refit_events/`
- `implementation_candidates/calibration_fit_recovery_interaction_recording/`

## Validated Boundary

The fixture validates a narrow interaction-recording boundary: explicit
user-declared fit recovery events can be applied to a workflow input and then
projected through existing recovery workflow and review-state summaries without
accepting GUI implementation, notebook execution, fit execution, scoring,
replay, registry, write-back, or hardware-control behavior.

The current fixture records seven synthetic interaction events:

- classify a readout incident as no clear signal;
- choose parameter adjustment and remeasurement for that incident;
- record a user note for the no-signal case;
- accept an adjusted visible-signal Rabi refit;
- record replay expectation context for the visible-signal case;
- select the visible-signal failed/refit attempts for lab-internal validation;
- select the visible incident in the local review surface.

The expected summary organizes that context into:

- applied event records;
- projected workflow and review-state summary identities;
- selected review incident id;
- recorded review context for the no-signal note and visible-signal replay
  expectation;
- incident-level interaction outcomes;
- an empty `missing_context` list for the complete main fixture;
- carried child workflow/review attention;
- explicit boundary non-claims.

## Important Separations

The main fixture and candidate mutation tests clarified several boundaries that
should be preserved:

- Interaction events are fixture-declared user facts, not captured GUI events,
  notebook commands, runner events, or a final interaction protocol.
- Applying events is a side-effect-free projection. It does not mutate stored
  measurements, parameters, code, notebooks, registries, or hardware state.
- Recovery actions remain user-declared choices. Scopecat records and validates
  them but does not choose one.
- The main fixture keeps no-signal remeasurement separate from validation
  selection; candidate mutation tests also reject no-signal final validation
  selection even when selection happened before reclassification.
- The main fixture preserves visible-signal failed/refit context; candidate
  mutation tests also prove selected visible-signal cases require failed/refit
  attempt context through the child workflow validation.
- Missing replay context is carried as attention. It is not a replay harness,
  runner request, or fit-code invocation.
- Dataset selection remains lab-internal validation state, not a portable
  package, public export, registry entry, or sharing bundle.

## Interaction Candidate

The tiny implementation candidate checks that the current read models can be
driven mechanically from explicit fixture events.

It assembles and validates:

- unique event identifiers and order values;
- supported event types only;
- event incident references against the workflow input;
- local review surface kind;
- signal-classification updates;
- recovery-action updates with available-action membership;
- review note and replay expectation updates;
- dataset-selection updates, while rejecting no-signal validation selection;
- selected review incident update;
- projected workflow and review-state summary ids;
- recorded review context for note and replay events;
- compact interaction outcomes derived from child summaries;
- child attention and missing replay context carried through unchanged.

The builder remains side-effect free. It does not render a GUI, execute fitting
code, read source data, select ROIs, generate initial guesses, run notebooks,
replay validation cases, remeasure, apply parameter writes, schedule work,
materialize a dataset registry, or control hardware.

## What The Fixture Can Answer

The current summary can answer:

- which user interaction events were applied and in what order;
- which incident was projected as no-signal remeasurement work;
- which incident can continue after an accepted visible-signal refit;
- which review context events recorded a note or replay expectation;
- which visible-signal validation case preserves the failed/refit attempt pair;
- which incident is selected in the local review state;
- whether selected cases are missing user-owned replay context;
- that the projection remains an internal validation summary rather than an
  export, registry, replay, fitting, notebook, or GUI contract.

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
- The event vocabulary covers only classification, recovery action, review
  context, dataset selection, and selected review incident.
- The summary does not prove that a real GUI or notebook-side interaction would
  feel continuous enough for users.
- Replay remains future user-owned intent. No harness, adapter, or fit-code
  invocation shape has been validated.

## Slice Recommendation

This slice is enough to keep interaction recording as a read-model candidate.
The next useful validation should either pressure ambiguous-signal or
multi-target interaction flows, or define a minimal user-owned replay/fit-code
handoff shape for selected validation cases.

Do not start a dataset registry, fitting API, automatic ROI or initial-guess
selection, parameter write-back, notebook execution, GUI implementation, or
hardware-control work from this slice.
