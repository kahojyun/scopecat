# Calibration Continuation Route Shape Validation Result

## Status

Fixture validation result with tiny route-shape candidate.

This is not an ADR, final route schema, GUI design, notebook integration,
fitting framework, score contract, analysis-result model, dataset registry,
replay harness, package/export format, runner design, remote-execution design,
write-back policy, or hardware-control decision. It records what the current
calibration continuation route-shape fixture proved and where the boundary
should remain narrow.

Artifact posture: fixture inputs are repository-safe synthetic fixtures, and
expected/candidate outputs declare `internal_validation_summary`. They are not
portable/public export datasets, GUI artifacts, notebook transcripts, replay
inputs, registry records, fit results, runner logs, measurement payloads, or
lab-sharing bundles.

## Inputs

- [`calibration-continuation-route-shape-validation-plan.md`](calibration-continuation-route-shape-validation-plan.md)
- [`calibration-continuation-route-input-contract-validation-result.md`](calibration-continuation-route-input-contract-validation-result.md)
- [`calibration-fit-recovery-interaction-recording-validation-result.md`](calibration-fit-recovery-interaction-recording-validation-result.md)
- [`calibration-fit-recovery-review-state-validation-result.md`](calibration-fit-recovery-review-state-validation-result.md)
- `tests/fixtures/calibration_continuation_route_shape/minimum_contract_with_degraded_context/`
- `implementation_candidates/calibration_continuation_route_shape/`

## Validated Boundary

The fixture validates a narrow route-shape boundary: a selected route input
contract can be projected into a static route view model that is renderable
with attention, without requiring upstream Vertical Productization first.

The current fixture includes:

- selected calibration continuation and fit recovery interaction inputs;
- a selected local review-state summary reference;
- unavailable setup binding and measurement preview support;
- reference-only parameter state and validation dataset draft context;
- fixture-declared route cards for incident-specific no-signal remeasurement
  and visible-signal accepted refit.

The expected summary organizes that context into:

- route shell state;
- fit recovery lane cards;
- context panel support/reference/optional context;
- continuation affordances for remeasurement, continuation, and dataset-add
  prompts;
- carried route input-contract attention;
- explicit boundary non-claims.

## Important Separations

The fixture clarified several boundaries that should be preserved:

- Route shape is a static internal validation summary, not a rendered GUI.
- Route cards are fixture-declared display facts with explicit allowed nested
  fields, not parsed child payloads, notebook events, or arbitrary passthrough
  objects.
- No-signal recovery is represented as remeasurement pressure before dataset
  selection.
- Visible-signal accepted refit is represented as continuable work with an
  optional lab-internal dataset-add prompt.
- Missing setup or preview context degrades the route with attention but does
  not force upstream Vertical Productization.
- Reference-only inputs are surfaced as chips without resolving or reading
  payloads.

## Route-Shape Candidate

The tiny implementation candidate checks that the current product-shape idea
can be produced mechanically from explicit fixture facts.

It assembles and validates:

- exact route shape policy posture;
- supported route shape kind;
- internal route input-contract posture;
- satisfied and internally consistent minimum route contract;
- continuation current-step alignment carried by the route input contract;
- selected fit recovery incident alignment with the fit interaction reference;
- route card states declared by incident-specific fit interaction outcomes;
- route-card signal classification and primary action consistency with route
  state;
- no-signal cards withholding dataset selection, selected case state, and case
  references before remeasurement;
- continuable visible-signal cards offering selected lab-internal dataset
  prompts with case references;
- allowed nested route-card field sets for primary actions and dataset prompts;
- rejection of nested payload fields such as fit results or measurement
  payloads;
- carried attention and context-panel reference-only state.

The builder remains side-effect free. It does not render a GUI, execute
calibration or fitting code, read measurement payloads, resolve references,
replay validation cases, apply parameter writes, schedule work, materialize a
dataset registry, emit a package, or control hardware.

## What The Fixture Can Answer

The current summary can answer:

- whether the route shape is renderable with missing-context attention;
- which incident is queued for remeasurement before dataset selection;
- which incident can continue after a user-accepted visible-signal refit;
- which incident receives a lab-internal dataset-add prompt;
- which supporting inputs are missing or reference-only;
- that the route shape remains an internal validation summary rather than a
  GUI, export, registry, replay, fitting, notebook, reference resolver, or
  hardware-control contract.

## Still Not Earned

This validation does not earn:

- GUI implementation;
- notebook integration;
- calibration execution;
- fitting implementation;
- fit model selection;
- Scopecat-defined score, pass/fail threshold, or scientific conclusion;
- measurement payload reading;
- reference resolution;
- automatic ROI selection, outlier rejection, or initial-guess generation;
- automatic remeasurement, retry, retune, or optimization;
- Scopecat-decided parameter write-back;
- local executor or notebook execution;
- replay harness;
- dataset registry service;
- portable/public dataset package;
- handoff artifact or lab-sharing bundle;
- hardware control.

## Remaining Risks

- The fixture is hand-authored and synthetic. It validates shape and boundary,
  not product usefulness.
- The route cards are display declarations. The slice does not prove how real
  GUI or notebook interactions would author them.
- The shape covers only one no-signal case and one visible-signal accepted
  refit case. It does not cover ambiguous signal, many targets, skipped
  targets, conflicting choices, or dataset versioning.
- Reference-only inputs remain unobserved. No resolver, importer, or payload
  reader has been validated.

## Slice Recommendation

This slice is enough to keep exploring the route-level product shape without
starting a GUI implementation. The next useful validation should pressure
ambiguous or multi-target fit recovery route cards, or define the minimal
user-owned replay/fit-code handoff shape needed when the user selects a case
for future fit-code improvement.

Do not start a dataset registry, fitting API, automatic ROI or initial-guess
selection, parameter write-back, reference resolver, notebook execution, GUI
implementation, or hardware-control work from this slice.
