# Calibration Continuation Route Input Contract Validation Plan

## Status

Validation-planning draft.

This is not an ADR, final route schema, GUI design, notebook integration,
fitting framework, score contract, analysis-result model, dataset registry,
replay harness, package/export format, runner design, remote-execution design,
write-back policy, or hardware-control decision. It defines a narrow validation
question for the minimum inputs a future calibration continuation route needs
before a product-shape prototype.

Related inputs:

- [`calibration-work-continuation-validation-result.md`](calibration-work-continuation-validation-result.md)
- [`calibration-fit-recovery-interaction-recording-validation-result.md`](calibration-fit-recovery-interaction-recording-validation-result.md)
- [`calibration-fit-recovery-review-state-validation-result.md`](calibration-fit-recovery-review-state-validation-result.md)

Artifact posture: planned fixture inputs should be repository-safe synthetic
fixtures, and expected outputs should declare `internal_validation_summary`.
The slice should not produce a GUI artifact, notebook transcript, dataset
package, handoff artifact, lab-sharing bundle, replay harness, registry entry,
runner log, measurement payload, or fit result.

## Validation Question

Can Scopecat define the calibration continuation route's minimum input
contract so a route-shape prototype may proceed from selected route-state
references while surfacing unavailable setup, preview, parameter, or replay
context as attention instead of requiring upstream Vertical Productization
first?

This slice should validate only the route input contract:

- the minimum route-shape contract inputs are selected calibration
  continuation state and fit recovery interaction state;
- supporting inputs can be selected, unavailable, reference-only, or optional;
- unavailable review-quality inputs become attention without claiming the
  upstream product is required;
- reference-only inputs are carried without reading or validating payloads;
- the contract remains a side-effect-free read model.

## User Job

Before building a route-level product shape, the user needs to know what facts
the calibration continuation route expects and what happens when some upstream
facts are missing.

The route input contract should help answer:

- which inputs are enough for a route-shape prototype to proceed;
- which missing facts degrade review quality but should not block exploration;
- which inputs are references owned by other slices;
- which future product-shape work can proceed without waiting for every
  upstream route to be verticalized.

## First Fixture Concept

Start with one synthetic public-safe fixture where the minimum route-shape
contract is satisfied but supporting context is incomplete:

- selected calibration work continuation summary reference;
- selected fit recovery interaction summary reference;
- selected fit recovery review-state summary reference;
- unavailable setup binding reference;
- unavailable measurement preview references;
- reference-only parameter state and validation dataset draft;
- optional prepared-run context not selected.

The fixture should be hand-authored and repository-safe. It should not include
real raw data, real paths, real hostnames, real sample labels, private
identifiers, or sensitive lab values. It should not run fitting code, read
source files, inspect notebooks, call hardware, mutate parameter state,
materialize a dataset registry entry, render a GUI, or emit a portable
artifact.

## Candidate Summary Shape

If the fixture earns a code-shaped experiment, the first candidate should be a
side-effect-free projection:

```text
CalibrationContinuationRouteInputContractInput
  -> build_calibration_continuation_route_input_contract_summary(...)
  -> CalibrationContinuationRouteInputContractSummary
```

The summary may include:

- `route_context`: fixture-declared route identity and current step;
- `input_contract`: route input readiness by family, role, owner, selected
  state, reference, or missing reason;
- `route_readiness`: whether minimum route-shape contract inputs are
  available;
- `missing_context`: unavailable route-render or review-quality inputs;
- `attention`: missing context, reference-only notes, and optional omissions;
- `boundary`: summary posture and explicit non-claims.

## Boundary

Do not include these in the first slice:

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
- hardware-control behavior;
- local executor or notebook execution;
- replay harness;
- dataset registry service;
- portable/public dataset package;
- handoff artifact or lab-sharing bundle.

Route inputs are fixture-declared facts only. They are not proof that the
upstream owner slice has a final product UI, stable public API, or completed
Vertical Productization.

## Done For This Planning Stage

This plan is sufficient when the next task can be stated as:

- create one route input-contract fixture;
- define expected summary output with input contract, route readiness, missing
  context, attention, and boundary;
- prove missing supporting inputs produce attention without requiring upstream
  productization;
- prove missing route-render inputs leave the minimum contract unsatisfied;
- keep GUI, notebook execution, fitting, scoring, replay, registry,
  write-back, reference resolution, and hardware behavior out of scope.
