# Calibration Step Fit Result Link Validation Result

## Status

Implementation candidate validated.

This result validates one narrow calibration workflow slice:
**Calibration Step Fit Result Link**.

It is not a final calibration step schema, fit-result schema, relation graph,
fitting framework, executor, scheduler, write-back contract, hardware-control
contract, storage model, workflow DAG, or GUI design.

Artifact posture: `internal_validation_summary`. This validation result, its
fixture input, and expected output are repository-safe discovery artifacts, not
portable/public export artifacts.

## Fixture

Fixture:
[`../../tests/fixtures/calibration_step_fit_result_link/basic_reference/`](../../../../tests/fixtures/calibration_step_fit_result_link/basic_reference)

Implementation candidate:
[`../../implementation_candidates/calibration_step_fit_result_link/`](../../../../implementation_candidates/calibration_step_fit_result_link)

The fixture records one qA Rabi calibration step record with a linked
measurement observation. A declared external fit-result summary references
that observation link and measurement record, exposes one parameter estimate,
and is cited by a proposed-write evidence reference.

## What This Earned

The implementation candidate shows that a side-effect-free summary can:

- link a calibration step record to a declared fit-result summary;
- require fit-result inputs to point at observation links belonging to the same
  step record;
- require fit-result input measurement records to match the observation link;
- project measurement-record summary facts without reading measurement
  payloads;
- carry declared model, config, code, estimate, uncertainty, and diagnostics
  summary fields without executing or scoring a fit;
- allow proposed writes to cite fit results as declared evidence while keeping
  write decision and apply state outside this slice;
- surface non-success or review-needed fit results as review findings instead
  of automatic refit, remeasurement, continuation, or write-back behavior;
- reject fixture claims that cross into fit execution, fit-quality scoring,
  model selection, write acceptance, parameter-store writes, compatibility
  output, hardware control, scheduling, or shared relation graph behavior.

## Boundary

This slice validates fit-result reference linkage only.

It does not:

- define final calibration step, fit-result, relation graph, lifecycle,
  storage, or package schemas;
- read measurement payloads or primary measurement data;
- run fitting, scoring, model selection, or scientific validity checks;
- execute calibration code or measurement code;
- decide continuation, retry, skip, refit, or remeasurement;
- create, accept, apply, emit, or roll back parameter writes;
- create committed parameter-state records;
- produce external compatibility output;
- control hardware;
- schedule work;
- recursively traverse adjacent records;
- define a GUI workflow.

## Result

Calibration step records can reference fit-result summaries without turning the
calibration route into a fitting engine.

The fit result is external declared evidence. It can connect a step observation
to parameter estimates and downstream proposed-write evidence refs, but it does
not decide whether those estimates are valid enough to write. Failed or
review-needed fit results become review findings, not automatic workflow
actions.

## Follow-Up

Stop this slice at declared fit-result linkage unless a concrete workflow needs
stronger behavior.

Likely follow-up slices should stay separate:

- fit-result comparison or recovery review, still without fitting execution or
  score policy;
- explicit accepted-write handoff to parameter-state management, still without
  hardware apply;
- compatibility-output planning from accepted parameter state, owned by the
  parameter-state route;
- dynamic fitting or replay only after fit execution authority is separately
  validated.
