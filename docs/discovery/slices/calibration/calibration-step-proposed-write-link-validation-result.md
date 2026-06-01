# Calibration Step Proposed Write Link Validation Result

## Status

Implementation candidate validated.

This result validates one narrow calibration workflow slice:
**Calibration Step Proposed Write Link**.

It is not a final calibration step schema, parameter-state schema, relation
graph, fitting framework, executor, scheduler, write-back contract,
hardware-control contract, storage model, workflow DAG, or GUI design.

Artifact posture: `internal_validation_summary`. This validation result, its
fixture input, and expected output are repository-safe discovery artifacts, not
portable/public export artifacts.

## Fixture

Fixture:
[`../../tests/fixtures/calibration_step_proposed_write_link/basic_review/`](../../../../tests/fixtures/calibration_step_proposed_write_link/basic_review)

Implementation candidate:
[`../../implementation_candidates/calibration_step_proposed_write_link/`](../../../../implementation_candidates/calibration_step_proposed_write_link)

The fixture records one qA Rabi calibration step record with resolved
parameter-state context and a reference-only observation link. A proposed write
links back to that step record and targets a parameter-state lineage/path with
before/after summary values.

## What This Earned

The implementation candidate shows that a side-effect-free summary can:

- link a calibration step record to a proposed parameter write;
- require the proposed write to target a known parameter-state lineage and
  parameter path;
- require the before-summary context to be a parameter-state snapshot already
  linked by the step record;
- keep proposed-write review state distinct from apply state;
- allow proposed, accepted-for-external-apply, and rejected review states while
  requiring `apply_state: not_applied`;
- surface pending proposed writes as review findings instead of automatic
  continuation, retry, correction, or write-back behavior;
- cite observation links as declared review evidence without reading
  measurement payloads;
- reject fixture claims that cross into parameter-store writes, hardware apply,
  committed parameter contexts, fitting, calibration execution, compatibility
  output, rollback, scheduling, or shared parameter schema behavior.

## Boundary

This slice validates reviewable proposed-write linkage only.

It does not:

- define final calibration step, parameter-state, relation graph, lifecycle,
  storage, or package schemas;
- read measurement payloads or primary measurement data;
- run fitting, scoring, or scientific validity checks;
- execute calibration code or measurement code;
- decide continuation, retry, skip, or remeasurement;
- apply, emit, or roll back parameter writes;
- create committed parameter-state records;
- produce external compatibility output;
- control hardware;
- schedule work;
- recursively traverse adjacent records;
- define a GUI workflow.

## Result

Calibration step records can carry links to proposed parameter writes without
becoming a write-back mechanism.

The proposed write is retrospective evidence from a step record plus a
prospective candidate value. Review can accept or reject the proposal, but this
slice still records no application. That keeps calibration review workflow
pressure separate from parameter-store authority and hardware-control
behavior.

`accepted_for_external_apply` is the early-adoption path: it records that a
user accepts the proposed value for action outside Scopecat, such as updating a
legacy parameter file or lab-owned tool. It does not create managed
parameter-state context, prove current hardware state, or imply Scopecat
write-back. The managed parameter-state path is validated separately by
[`calibration-accepted-write-handoff-validation-result.md`](calibration-accepted-write-handoff-validation-result.md),
which requires `accepted_for_parameter_state_handoff` before handing the
proposal to parameter-state-owned intake/storage.

## Follow-Up

Stop this slice at review-only proposed writes unless a concrete workflow needs
stronger behavior.

Likely follow-up slices should stay separate:

- calibration fit-result reference shape, still without fitting execution or
  score semantics;
- explicit accepted-write handoff to parameter-state management, still without
  hardware apply;
- compatibility-output planning from accepted parameter state, owned by the
  parameter-state route;
- dynamic application or rollback only after parameter-store authority is
  separately validated.
