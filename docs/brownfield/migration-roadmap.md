# Brownfield Migration Roadmap

## Status

Current use-case-driven migration roadmap.

## Purpose

Sequence brownfield migration by validated use cases implemented as thin
slices. This is a roadmap for product and architecture sequencing, not an
implementation task list, release plan, or issue tracker.

## Sequencing Principles

- Advance by named use cases, not by shared domain model extraction.
- Prefer review, package, record, and bridge value before execution or hardware
  authority.
- Make every slice name a user-visible use case or workflow segment.
- Keep legacy-specific parsing and target product concepts separate.
- Promote shared domain concepts only after repeated slices need the same
  stable contract.
- Use target journeys for user-recognizable end-to-end jobs. Keep reusable
  context and comparison work as supporting workflows until a consuming journey
  proves an independent user goal.

## Current Migration Sequence

### 1. Harden Share A Selected Measurement

Target journey: JNY-001.

Target use case: UC-006 and JNY-001-SMOKE.

Related risks: BR-RISK-003, BR-RISK-004, BR-RISK-010.

Related decisions: DEC-003, DEC-004, DEC-010, DEC-011, DEC-021, DEC-024,
DEC-025.

Next validation focus:

- decide whether the selected-record handoff path needs production-readiness
  hardening, batch export productization, linked-context payload follow-up, or a
  different product fork.

Already validated:

- selected stored-record package export;
- local package writing/opening from declared source-root data;
- safe zip archive creation and materialization around the DEC-010 package of
  record;
- receiving-side read-only package review, import plan, review-state receipt,
  and accepted new-record durable import.

Decision gate:

- handoff hardening remains centered on sharing a selected Measurement Record,
  not on absorbing Measurement Record creation, adoption, running updates, or
  completed-record finalization.

### 2. Stabilize Prepare A Manual Run

Target journey: JNY-002.

Target use case: UC-CAND-002.

Related risks: BR-RISK-001, BR-RISK-007, BR-RISK-008, BR-RISK-009.

Related decisions: DEC-006.

Next validation focus:

- decide whether prepared-run context review becomes a live route owner or
  remains discovery evidence.

Already validated:

- adapter-authored parameter-state intake;
- parameter-state storage and read view;
- source-agnostic parameter-state selection;
- route-local pre-run parameter-state consumption;
- bounded environment-operation evidence.

Decision gate:

- a user-facing prepared-run use case has explicit input, review,
  acknowledgement or deferral, no-run-start semantics, and a receipt shape that
  a later Measurement Record can reference as context evidence.

### 3. Split Record Or Adopt A Measurement From Handoff

Target journey: JNY-007.

Target use case: UC-001 and UC-002 as current supporting use cases; promote a
new candidate only when adoption/recording needs a user-facing route beyond
handoff scaffolding.

Related risks: BR-RISK-003, BR-RISK-004, BR-RISK-011.

Related decisions: DEC-004, DEC-025.

Next validation focus:

- decide whether record/adopt is a standalone user journey now or remains a
  Measurement Records capability path feeding JNY-001.

Already validated:

- legacy-backed measurement record shell and storage visibility;
- normalized primary-data durable import;
- record-local references and local storage review surfaces.

Decision gate:

- a user-facing recording/adoption use case has explicit source posture,
  reviewed primary-data handling, repository-safe context references, and clear
  non-claims around legacy execution, adapter discovery, and scientific
  validity.

### 4. Validate Monitor A Running Measurement

Target journey: JNY-004.

Target use case: UC-CAND-004.

Related risks: BR-RISK-001, BR-RISK-007.

Related decisions: DEC-001.

Next validation focus:

- prove explicit lifecycle/progress/partial-data event recording from
  Python-driven measurements.

Already validated:

- discovery evidence and related Measurement Records inspection pressure.

Decision gate:

- monitoring provides review value without becoming scan control, scheduling,
  automatic retune, or execution ownership.

### 5. Define Review And Finalize A Completed Measurement

Target journey: JNY-008.

Target use case: candidate to define from Measurement Records review/finalize
pressure.

Related risks: BR-RISK-003, BR-RISK-006, BR-RISK-007, BR-RISK-010.

Related decisions: DEC-025.

Next validation focus:

- decide whether post-run record review/finalization needs a route owner before
  more handoff hardening.

Already validated:

- record read-model projection and refresh;
- selected-record export freshness review;
- local operator review artifacts and receipts.

Decision gate:

- a completed-record review use case has explicit readiness semantics for
  handoff, comparison, calibration continuation, or rerun preparation without
  replacing canonical source evidence.

### 6. Reassess Recover Or Continue Calibration Work

Target journey: JNY-003.

Target use case: UC-CAND-005.

Related risks: BR-RISK-001, BR-RISK-005, BR-RISK-007.

Related decisions: DEC-002, DEC-005.

Next validation focus:

- decide whether calibration continuation is a repeated product capability or
  remains scenario evidence.

Already validated:

- reviewable fit, action, and continuation summaries;
- accepted calibration write handoff pressure into parameter-state review.

Decision gate:

- repeated use cases require stable calibration review state, continuation
  action recording, and support expectations beyond one scenario.

### 7. Shape Reproduce Or Rerun From A Reference

Target journey: JNY-009.

Target use case: future candidate composed from selected-reference comparison
and experiment-code context evidence.

Related risks: BR-RISK-005, BR-RISK-007, BR-RISK-009.

Related decisions: DEC-002, DEC-008.

Next validation focus:

- choose whether the first concrete step is reference selection, declared
  context comparison, selected-code comparison, workspace materialization, or
  rerun preparation.

Already validated:

- selected-reference comparison discovery evidence;
- discovery and implementation-candidate evidence for code-context recording;
- bounded environment-operation evidence for `uv sync` review;
- candidate materialization and environment-readiness evidence.

Decision gate:

- the selected reproduction/rerun use case has a user goal independent of
  generic Git replacement, package management, or experiment execution
  ownership.

## Deferred Cross-Cutting Work

Defer until multiple validated use cases need the same contract:

- shared measurement/context domain model extraction;
- generalized artifact parser framework;
- universal setup, sample, topology, or parameter ontology;
- broad runtime readiness framework;
- hardware apply and live write-back authority;
- general driver, scan, service, or scheduling ownership.

## Update Rule

Update this roadmap when the next validation focus, sequencing principles, or
decision gates change.

Do not use this file to list tasks, owners, deadlines, test names, fixtures, or
implementation modules.
