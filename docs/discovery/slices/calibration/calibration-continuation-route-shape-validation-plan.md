# Calibration Continuation Route Shape Validation Plan

## Status

Validation-planning draft.

This is not an ADR, final route schema, GUI design, notebook integration,
fitting framework, score contract, analysis-result model, dataset registry,
replay harness, package/export format, runner design, remote-execution design,
write-back policy, or hardware-control decision. It defines a narrow validation
question for a static product-shape view model over the calibration
continuation route input contract.

Related inputs:

- [`calibration-continuation-route-input-contract-validation-result.md`](calibration-continuation-route-input-contract-validation-result.md)
- [`calibration-fit-recovery-interaction-recording-validation-result.md`](calibration-fit-recovery-interaction-recording-validation-result.md)
- [`calibration-fit-recovery-review-state-validation-result.md`](calibration-fit-recovery-review-state-validation-result.md)

Artifact posture: planned fixture inputs should be repository-safe synthetic
fixtures, and expected outputs should declare `internal_validation_summary`.
The slice should not produce a GUI artifact, notebook transcript, dataset
package, handoff artifact, lab-sharing bundle, replay harness, registry entry,
runner log, measurement payload, or fit result.

## Validation Question

Can Scopecat project the calibration continuation route input contract into a
static route shape that shows the user what can happen next when the minimum
contract is satisfied but setup, preview, replay, or reference context is still
missing or reference-only?

This slice should validate only the route shape:

- the route can be renderable with attention when minimum inputs are selected;
- no-signal fit recovery is shown as remeasurement work before dataset
  selection;
- visible-signal accepted refit is shown as continuable work with a
  lab-internal dataset-add prompt;
- missing setup or preview context remains review attention;
- reference-only context is surfaced without resolving or reading payloads.

## User Job

When a fit recovery happens during calibration, the user first needs to keep
the experiment moving. The route should show whether they should remeasure,
adjust/refit, continue, or add the failed/refit pair to a validation dataset
draft, without requiring them to manually assemble context from disconnected
workflow summaries.

The route shape should help answer:

- whether the route is blocked or renderable with missing-context attention;
- which fit recovery incident still needs remeasurement;
- which accepted visible-signal refit can continue;
- which selected validation case can be offered as lab-internal dataset
  material;
- which upstream facts are missing or only carried by reference.

## First Fixture Concept

Start with one synthetic public-safe fixture that consumes the route input
contract summary from the previous slice:

- minimum route contract is satisfied with attention;
- selected fit recovery interaction reference declares incident-specific
  no-signal and continuable accepted-refit outcomes;
- setup binding and measurement preview are unavailable review-quality inputs;
- parameter state and validation dataset draft are reference-only;
- route cards are fixture-declared display facts with explicit allowed fields,
  not payload reads or nested passthrough surfaces.

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
CalibrationContinuationRouteShapeInput
  -> build_calibration_continuation_route_shape_summary(...)
  -> CalibrationContinuationRouteShapeSummary
```

The summary may include:

- `route_context`: copied from the route input contract summary;
- `route_shell`: static route state, selected incident, and attention count;
- `fit_recovery_lane`: route cards for no-signal and visible-signal recovery;
- `context_panel`: missing support, reference chips, and optional context;
- `continuation_affordances`: remeasurement queue, continuation targets, and
  dataset-add prompts;
- `attention`: carried route input-contract attention;
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
