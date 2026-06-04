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
- Distinguish actual adoption order from design validation order. Adoption can
  start where local pain is strongest; design sequencing should preserve the
  Measurement Record anchor, review receipts, package/export boundaries, and
  authority non-claims.

## Adoption Order Versus Design Order

Brownfield adoption is opportunity-driven. A lab may reasonably start from
handoff, parameter review, running monitoring, calibration continuation, or a
specific fragile legacy boundary depending on current pain and integration
cost.

This roadmap is a design validation sequence. It orders slices to keep
dependencies and authority boundaries coherent:

```text
evidence and source posture
  -> Measurement Record anchor
  -> post-run review and prepared-run receipts
  -> handoff, comparison, running, calibration, or rerun extensions
```

If an adoption path starts later in the lifecycle, keep the same boundary
rules: record evidence explicitly, avoid run-start or hardware-control creep,
and link new review outputs back to the Measurement Record or another named
Scopecat boundary when the use case needs continuity.

## Current Migration Sequence

This sequence follows the current-state-to-target migration spine. It is not a
historical implementation order. JNY-001 already has the strongest vertical
slice evidence and can continue to harden in parallel; the order below is for
validating cleaner product boundaries before splitting or promoting more code.

`Already validated` records evidence that exists for the boundary. It may
include discovery validation slices, engineering prototype slices,
implementation-candidate evidence, and production vertical slice segments.
Treat the maturity labels in the workflow validation map as authoritative; do
not read every `Already validated` bullet as a maintained product capability.

### 1. Make External Runs Visible

Target boundary: JNY-007 Record Or Adopt A Measurement, supported by CAP-001
Measurement Records.

Target use case: UC-001 and UC-002 as current supporting use cases; promote a
new candidate only when adoption or recording needs a user-facing route beyond
Measurement Records scaffolding.

Related risks: BR-RISK-003, BR-RISK-004, BR-RISK-011.

Related decisions: DEC-004, DEC-025.

Next validation focus:

- decide which first user-facing route or use case should own recording/adoption
  beyond the existing Measurement Records capability path feeding JNY-001 and
  JNY-008.

Already validated:

- legacy-backed measurement record shell and storage visibility;
- normalized primary-data durable import;
- record-local references and local storage review surfaces.

Decision gate:

- a user-facing recording/adoption use case has explicit source posture,
  reviewed primary-data handling, repository-safe context references, and clear
  non-claims around legacy execution, adapter discovery, and scientific
  validity.

### 2. Select Measurements For Sharing

Target boundary: JNY-001 Share A Selected Measurement.

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
  post-run results review.

### 3. Check Context Before A Run

Target boundary: JNY-002 Prepare A Manual Run.

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

### 4. Maintain Parameter And Setup Files

Target boundary: CAP-003 Parameter State Review, setup-binding support, and
JNY-002 supporting workflow coverage. This is not promoted to a target journey
until the work has an independent user goal beyond prepared-run context review
or calibration continuation support.

Target use case: candidate to define from parameter-history, parameter-plot,
setup-binding, or review-summary pressure.

Related risks: BR-RISK-005, BR-RISK-007, BR-RISK-008, BR-RISK-009.

Related decisions: DEC-002, DEC-006, DEC-008.

Next validation focus:

- decide which parameter/setup maintenance work is needed first by
  prepared-run review: history, comparison, plotting, setup-binding snapshot,
  adapter summary, or accepted-write review.

Already validated:

- adapter-authored parameter-state intake;
- parameter-state storage and read view;
- source-agnostic parameter-state selection;
- route-local pre-run parameter-state consumption;
- reviewable calibration action and continuation summaries that create
  accepted-write pressure.

Decision gate:

- parameter/setup work remains a capability or supporting workflow unless a
  repeated independent user job emerges; it must not imply hardware apply,
  live-instrument state ownership, universal setup truth, or broad runtime DLP.

### 5. Review Completed Results

Target boundary: JNY-008 Browse And Review Completed Results.

Target use case: candidate to define from post-run result browsing, filtering,
plotting, and Measurement Records readiness-review pressure.

Related risks: BR-RISK-003, BR-RISK-006, BR-RISK-007, BR-RISK-010.

Related decisions: DEC-025.

Next validation focus:

- choose the first live post-run route or use case: records browser, plotter,
  readiness-review receipt, or a narrow composition of those surfaces.

Already validated:

- record read-model projection and refresh;
- selected-record export freshness review;
- local operator review artifacts and receipts.

Decision gate:

- a post-run results review use case lets users find, inspect, plot, and assess
  completed or near-completed results before handoff, comparison, calibration
  continuation, or rerun preparation without replacing canonical source
  evidence.

### 6. Inspect Running Measurements

Target boundary: JNY-004 Monitor A Running Measurement.

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

### 7. Continue Calibration Work

Target boundary: JNY-003 Recover Or Continue Calibration Work.

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

### 8. Reconstruct A Reference Or Rerun

Target boundary: JNY-009 Reproduce Or Rerun From A Reference.

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
