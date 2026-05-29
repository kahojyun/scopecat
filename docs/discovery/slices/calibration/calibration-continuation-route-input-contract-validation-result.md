# Calibration Continuation Route Input Contract Validation Result

## Status

Fixture validation result with tiny input-contract candidate.

This is not an ADR, final route schema, GUI design, notebook integration,
fitting framework, score contract, analysis-result model, dataset registry,
replay harness, package/export format, runner design, remote-execution design,
write-back policy, or hardware-control decision. It records what the current
calibration continuation route input-contract fixture proved and where the
boundary should remain narrow.

Artifact posture: fixture inputs are repository-safe synthetic fixtures, and
expected/candidate outputs declare `internal_validation_summary`. They are not
portable/public export datasets, GUI artifacts, notebook transcripts, replay
inputs, registry records, fit results, runner logs, measurement payloads, or
lab-sharing bundles.

## Inputs

- [`calibration-continuation-route-input-contract-validation-plan.md`](calibration-continuation-route-input-contract-validation-plan.md)
- [`calibration-work-continuation-validation-result.md`](calibration-work-continuation-validation-result.md)
- [`calibration-fit-recovery-interaction-recording-validation-result.md`](calibration-fit-recovery-interaction-recording-validation-result.md)
- [`calibration-fit-recovery-review-state-validation-result.md`](calibration-fit-recovery-review-state-validation-result.md)
- `tests/fixtures/calibration_continuation_route_input_contract/minimum_render_with_missing_support/`
- `implementation_candidates/calibration_continuation_route_input_contract/`

## Validated Boundary

The fixture validates a narrow route input-contract boundary: the route can
declare selected minimum route-shape inputs and carry missing or reference-only
supporting inputs without requiring upstream Vertical Productization first.

The current fixture includes:

- selected calibration work continuation summary reference;
- selected fit recovery interaction summary reference;
- selected fit recovery review-state summary reference;
- unavailable setup binding reference;
- unavailable measurement preview references;
- reference-only parameter state and validation dataset draft;
- optional prepared-run context not selected.

The expected summary organizes that context into:

- input contract records;
- route readiness;
- missing-context findings for unavailable review-quality inputs;
- attention for missing, reference-only, and optional inputs;
- explicit boundary non-claims.

## Important Separations

The fixture clarified several boundaries that should be preserved:

- Minimum route-shape contract inputs are distinct from supporting
  review-quality inputs.
- Missing setup binding or preview context can degrade the route with attention
  without requiring those upstream routes to be productized first.
- Reference-only inputs are carried by reference and not opened, resolved,
  validated, or imported by this route.
- The route input contract is not a product UI, runner, scheduler, fit
  execution plan, write-back path, replay harness, dataset registry, package,
  or hardware-control surface.

## Input-Contract Candidate

The tiny implementation candidate checks that the current contract can be
produced mechanically from explicit fixture facts.

It assembles and validates:

- exact route input policy posture;
- supported input families;
- supported include states;
- supported `required_for` classes;
- unique route input identifiers;
- unique family/role pairs;
- selected and reference-only inputs carrying references;
- unavailable inputs carrying missing reasons and no references;
- optional inputs staying optional;
- minimum route-render families being present;
- missing route-render input behavior as an unsatisfied minimum contract;
- missing review-quality input attention;
- reference-only input attention.

The builder remains side-effect free. It does not render a GUI, execute
calibration or fitting code, read measurement payloads, resolve references,
replay validation cases, apply parameter writes, schedule work, materialize a
dataset registry, emit a package, or control hardware.

## What The Fixture Can Answer

The current summary can answer:

- which input families satisfy the minimum route-shape contract;
- which supporting input families are unavailable;
- which missing inputs are attention rather than upstream productization
  blockers;
- which inputs are only carried as references;
- whether the declared minimum input set is satisfied for a later route-shape
  prototype;
- that the contract remains an internal validation summary rather than an
  export, registry, replay, fitting, notebook, GUI, reference resolver, or
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
- The minimum input set may change after a route-level product-shape prototype.
- The contract does not prove that a real GUI or notebook-side interaction
  would feel continuous enough for users.
- Reference-only inputs remain unobserved. No resolver, importer, or payload
  reader has been validated.

## Slice Recommendation

This slice is enough to support a route-level product-shape prototype without
waiting for every upstream prerequisite to be verticalized. The next useful
validation should compose this contract into a static route shape or view model
that shows what the user sees when the minimum contract is satisfied but
degraded by missing setup or preview context.

Do not start a dataset registry, fitting API, automatic ROI or initial-guess
selection, parameter write-back, reference resolver, notebook execution, GUI
implementation, or hardware-control work from this slice.
