# Calibration Fit Validation Dataset Validation Result

## Status

Fixture validation result with tiny assembler candidate.

This is not an ADR, final workflow model, fitting framework, score contract,
analysis-result model, dataset registry, replay harness, package/export format,
GUI design, runner design, retry policy, write-back policy, remote-execution
design, or hardware-control decision. It records what the current fit
validation dataset fixture proved and where the boundary should remain narrow.

Artifact posture: `internal_validation_summary`. The fixture and expected
output are repository-safe validation artifacts, not portable/public export
datasets.

## Inputs

- [`brief`](../../problem-briefs/calibration-fit-validation-dataset.md)
- [`validation plan`](calibration-fit-validation-dataset-validation-plan.md)
- `tests/fixtures/calibration_fit_validation_dataset/basic_candidate_queue/`
- `implementation_candidates/calibration_fit_validation_dataset/`

## Validated Boundary

The fixture validates a first boundary for fit validation dataset exploration
as fit-incident queue assembly and selected-case projection, not fitting,
scoring, replay, or dataset registry behavior.

The current fixture represents three user-reviewed incidents:

- no meaningful signal, where the immediate action is parameter adjustment and
  remeasurement rather than validation-case inclusion;
- visible signal with failed fit, where ROI or initial-guess refit is the
  immediate recovery action and the case is selected for validation;
- accepted-after-review readout fitting, where the user accepted the current
  result but still selected the suspicious case as a future regression case.

The expected summary organizes that context into:

- ordered candidate queue;
- immediate recovery actions;
- selected validation case records;
- lab-internal dataset draft;
- attention findings for selected cases missing replay context;
- explicit boundary non-claims.

## Important Separations

The fixture clarified several boundaries that should be preserved:

- Fit incidents are user-owned review facts, not Scopecat fit results.
- Recovery choices and dataset curation are related but distinct. A user may
  remeasure, refit, accept, skip, or add a case without Scopecat choosing the
  action.
- A no-signal case is ordinary recovery state. It is not automatically a
  validation dataset case.
- Selected validation cases require enough user-owned replay context to be
  useful later: source measurement, fit attempt, user-code reference, fit
  config, review note, and expected replay behavior.
- The lab-internal dataset draft is not a portable/export package.

## Assembler Candidate

The tiny implementation candidate checks that the current read model can be
produced mechanically from explicit fixture facts without silently inventing
fit outputs or replay behavior.

It assembles and validates:

- unique fit-incident identifiers;
- unique derived validation case identifiers for selected cases;
- chosen recovery action membership in available actions;
- queue summaries from declared incident facts;
- recovery action records as user choices;
- selected incidents into minimal validation case records;
- readiness findings when selected cases lack replay context;
- readiness findings when the draft posture is outside the validated
  lab-internal boundary.

The builder remains side-effect free. It does not execute fitting code, read
source data, select ROIs, reject outliers, run notebooks, remeasure, apply
parameter writes, schedule work, or control hardware.

## What The Fixture Can Answer

The current summary can answer:

- which fit incidents are waiting for review or recovery;
- which immediate recovery action was chosen for each incident;
- which incidents were selected for validation dataset inclusion;
- which no-signal incident was withheld from the dataset draft;
- which minimal validation case records would be available for future replay;
- whether selected cases are missing replay context;
- that the dataset draft is lab-internal validation state, not export/package
  output.

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
- general-purpose analysis or ML dataset infrastructure;
- hardware control.

## Remaining Risks

- The fixture is hand-authored and synthetic. It validates shape and boundary,
  not product usefulness.
- The fixture covers only three incident types. It does not cover ambiguous
  data quality, multiple repeated fit attempts, conflicting user labels,
  partial raw-data availability, selected cases with private context, or
  dataset versioning.
- The summary does not prove that users will accept the candidate queue in the
  middle of calibration work.
- Replay is only represented as future user-owned intent. No harness, adapter,
  or code invocation shape has been validated.

## Slice Recommendation

Continue with one richer fixture before designing a dataset registry or replay
harness.

The next fixture should pressure repeated user-owned fit attempts on the same
measurement: failed default fit, adjusted ROI or initial guess, accepted or
still failed outcome, and final decision to add or withhold the case. That
would test whether the queue needs first-class attempt history before any GUI,
registry, or replay adapter work.

Do not start fit execution, scoring, automatic ROI selection, remeasurement,
write-back, or hardware-control work from this slice.
