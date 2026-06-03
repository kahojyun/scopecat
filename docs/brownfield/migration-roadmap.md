# Brownfield Migration Roadmap

## Status

Current vertical-slice migration roadmap.

## Purpose

Sequence brownfield migration by validated vertical slices. This is a roadmap
for product and architecture sequencing, not an implementation task list,
release plan, or issue tracker.

Use this document to decide which user-visible migration slice should be proved
next. Use [`../engineering/workflow-validation-map.md`](../engineering/workflow-validation-map.md)
for detailed validation state and
[`../engineering/implementation-register.md`](../engineering/implementation-register.md)
for live implementation ownership.

## Sequencing Principles

- Advance by vertical slice, not by shared domain model extraction.
- Prefer review, package, record, and bridge value before execution or hardware
  authority.
- Make every slice name a user-visible use case or workflow segment.
- Keep legacy-specific parsing and target product concepts separate.
- Promote shared domain concepts only after repeated slices need the same
  stable contract.

## Current Migration Sequence

### 1. Close Portable Measurement Handoff

Target journey: Portable Measurement Handoff.

Next vertical-slice pressure:

- export one selected stored Measurement Record to a preview-ready
  single-measurement handoff package.

Already validated:

- legacy-backed measurement record shell and storage visibility;
- normalized primary-data durable import;
- local package writing/opening from declared source-root data;
- receiving-side read-only package review, import plan, and accepted durable
  import.

Decision gate:

- package export from stored Measurement Records preserves identity,
  primary-data references, missing context, and portable/export artifact
  boundaries clearly enough to connect the two validated ends.

### 2. Stabilize Pre-Run Context Review

Target journey: Pre-Run Context Review.

Next vertical-slice pressure:

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
  acknowledgement or deferral, and no-run-start semantics.

### 3. Promote One Experiment Code Context Step

Target journey: Experiment Code Context Recovery And Reuse.

Next vertical-slice pressure:

- choose one concrete step: record, compare, materialize, observe editable
  folder, prepare rerun, or GUI review.

Already validated:

- discovery and implementation-candidate evidence for code-context recording;
- bounded environment-operation evidence for `uv sync` review;
- candidate materialization and environment-readiness evidence.

Decision gate:

- the selected step has a user goal independent of generic Git replacement or
  execution ownership.

### 4. Validate Running Measurement Monitoring

Target journey: Running Measurement Monitoring And Inspection.

Next vertical-slice pressure:

- prove explicit lifecycle/progress/partial-data event recording from
  Python-driven measurements.

Already validated:

- discovery evidence and related Measurement Records inspection pressure.

Decision gate:

- monitoring provides review value without becoming scan control, scheduling,
  or automatic retune.

### 5. Reassess Calibration Continuation

Target journey: Calibration Work Continuation.

Next vertical-slice pressure:

- decide whether calibration continuation is a repeated product capability or
  remains scenario evidence.

Already validated:

- reviewable fit, action, and continuation summaries;
- accepted calibration write handoff pressure into parameter-state review.

Decision gate:

- repeated use cases require stable calibration review state, continuation
  action recording, and support expectations beyond one scenario.

## Deferred Cross-Cutting Work

Defer until multiple vertical slices need the same contract:

- shared measurement/context domain model extraction;
- generalized artifact parser framework;
- universal setup, sample, topology, or parameter ontology;
- broad runtime readiness framework;
- hardware apply and live write-back authority;
- general driver, scan, service, or scheduling ownership.

## Update Rule

Update this roadmap when the next vertical-slice pressure, sequencing
principles, or decision gates change.

Do not use this file to list tasks, owners, deadlines, test names, fixtures, or
implementation modules.
