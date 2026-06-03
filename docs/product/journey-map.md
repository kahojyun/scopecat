# Product Journey Map

## Status

Current product journey map.

## Purpose

Own Scopecat's product-facing user journeys and the first decomposition from
discovery evidence into workflows and use cases. This is a product planning
document, not an implementation register, scenario inventory, or engineering
task plan.

Use this document with:

- [`adoption-model.md`](adoption-model.md), for how users start adopting
  Scopecat around brownfield systems;
- [`capability-map.md`](capability-map.md), for product capabilities and
  candidate feature areas;
- [`../engineering/workflow-validation-map.md`](../engineering/workflow-validation-map.md),
  for validation state of use cases, workflow segments, scenarios, operations,
  and seams;
- [`../engineering/implementation-register.md`](../engineering/implementation-register.md),
  for live implementation ownership.

## Reading Rules

Start here before promoting discovery evidence into `src/`. A discovery slice
should attach to one of these journeys, a named use case under a journey, or an
explicit evidence-only scenario or operation in the engineering validation map.

Do not create a code owner from a journey name by default. Journeys organize
product intent; implementation owners remain in the implementation register.

## Journey Catalog

### Legacy Measurement Portable Handoff

Goal: move one selected legacy-backed measurement from one Scopecat storage
root to another computer where it can be previewed and imported.

Primary workflows:

- local record preparation;
- selected measurement package export;
- receiving-side package review;
- durable import after explicit acceptance.

Use cases to prove:

- record legacy run facts locally;
- attach reviewed normalized primary data;
- export one selected stored Measurement Record to a handoff package;
- open a package read-only;
- build a non-mutating import plan;
- import one approved package measurement into durable local storage.

Supporting capabilities:

- Measurement Records;
- Handoff Packages;
- Experiment Code Context later;
- Parameter State Review later.

Current product posture: primary active journey. Engineering prototypes cover
local record preparation, package writing/opening, receiving review/import
plan, and durable import adaptation. The main missing use case is selected
stored Measurement Record to single-measurement package export.

Source evidence:

- [`selected-run-handoff.md`](../discovery/problem-briefs/selected-run-handoff.md);
- [`measurement-record-boundary.md`](../discovery/problem-briefs/measurement-record-boundary.md).

### Manual Pre-Run Context Review And Approval

Goal: review selected parameter, code, environment, and setup context before a
manual run without giving Scopecat execution or hardware-control authority.

Primary workflows:

- parameter-state intake and review;
- context selection;
- prepared-run review;
- optional environment-operation evidence;
- operator approval.

Use cases to prove:

- import and review adapter-authored parameter state;
- store and read reviewed parameter state;
- select source-agnostic parameter state for run preparation;
- consume parameter-state facts in a prepared-run review chain;
- capture bounded environment-operation evidence;
- record code context for a run or step;
- later add setup-binding snapshot selection.

Supporting capabilities:

- Parameter State Review;
- Experiment Code Context;
- Environment Operation;
- Measurement Records context links;
- setup-binding candidate workflow.

Current product posture: parameter-state review has live engineering prototype
coverage. Prepared-run context and approval remain scenario evidence without a
live route owner. Environment operation is operation evidence for later
readiness/context use, not a standalone journey.

Source evidence:

- [`parameter-state-management.md`](../discovery/problem-briefs/parameter-state-management.md);
- [`experiment-code-recording.md`](../discovery/problem-briefs/experiment-code-recording.md);
- [`setup-binding.md`](../discovery/problem-briefs/setup-binding.md).

### Calibration Work Continuation

Goal: recover or continue multi-step calibration work using reviewable fit,
evidence, action, and continuation state instead of scattered notebook state.

Primary workflows:

- calibration step intent and observation recording;
- fit review;
- user action recording;
- continuation composition;
- accepted write handoff into parameter-state review.

Use cases to prove:

- review a failed calibration fit;
- record a continuation decision or recovery action;
- block downstream steps until review is accepted;
- hand off accepted calibration writes to parameter-state review;
- later test whether a small local sequential executor is needed.

Supporting capabilities:

- candidate Calibration Continuation Review;
- Parameter State Review;
- Measurement Records context links;
- Experiment Code Context later.

Current product posture: candidate feature area with discovery and
implementation-candidate evidence. It should not become a live route owner
until a narrow calibration continuation use case has acceptance criteria.

Source evidence:

- [`calibration-work-continuation.md`](../discovery/problem-briefs/calibration-work-continuation.md);
- [`calibration-fit-validation-dataset.md`](../discovery/problem-briefs/calibration-fit-validation-dataset.md).

### Running Measurement Monitoring And Inspection

Goal: inspect progress and already-recorded useful data from long-running
measurements before the full run finishes.

Primary workflows:

- explicit lifecycle/progress recording;
- partial-data read and inspection;
- readiness/completeness classification;
- optional saved fit or operator decision.

Use cases to prove:

- emit lifecycle, progress, and partial-data events from Python measurement
  scripts;
- inspect the latest useful sweep;
- classify whether recorded data is partial or ready;
- later save selected range fits or operator decisions.

Supporting capabilities:

- Running Measurement Monitor;
- Measurement Records;
- optional app runtime.

Current product posture: discovery and validation-question stage. No live
product capability owner yet beyond related Measurement Records inspection
evidence.

Source evidence:

- [`running-measurement-inspection.md`](../discovery/problem-briefs/running-measurement-inspection.md).

### Experiment Code Context Recovery And Reuse

Goal: know which code context was associated with a run, calibration step,
handoff, or comparison so it can later be reviewed, compared, restored, or
migrated.

Primary workflows:

- explicit code-context recording;
- selected-code comparison;
- workspace materialization;
- environment readiness review.

Use cases to prove:

- record run/step code context with entrypoint and include policy;
- compare selected recorded-code context;
- prepare a selected code workspace for rerun;
- capture environment readiness or operation evidence without executing
  experiment code.

Supporting capabilities:

- Experiment Code Context;
- Environment Operation;
- Measurement Records;
- Handoff Packages later.

Current product posture: discovery and implementation-candidate evidence.
Environment Operation currently provides operation evidence for bounded
`uv sync`, not a full code-context or runtime-readiness journey.

Source evidence:

- [`experiment-code-recording.md`](../discovery/problem-briefs/experiment-code-recording.md).

### Selected Reference Comparison

Goal: compare a current measurement or context bundle against a user-selected
reference and surface objective findings without claiming user/domain judgment.

Primary workflows:

- reference selection;
- declared-context comparison;
- code-context comparison;
- finding review.

Use cases to prove:

- mark or select a reference record;
- compare declared measurement/context facts;
- compare selected code context;
- classify changed, missing, unverified, redacted, unlinked, same-observed, and
  not-compared facts.

Supporting capabilities:

- Measurement Records;
- Experiment Code Context;
- Parameter State Review;
- setup-binding candidate workflow.

Current product posture: discovery evidence. The first credible use case is
comparison over declared context, not a universal setup truth or judgment
engine.

Source evidence:

- [`selected-reference-comparison.md`](../discovery/problem-briefs/selected-reference-comparison.md);
- [`setup-binding.md`](../discovery/problem-briefs/setup-binding.md).

## Supporting Workflow Candidates

Supporting workflows may become use cases under one or more journeys, but they
are not user journeys by themselves yet.

### Setup Binding Snapshot And Diff Review

Supports:

- manual pre-run context review;
- selected reference comparison;
- legacy handoff context.

Why it is not a journey yet: the evidence shows a reusable context family, but
no complete user journey starts and ends with setup binding alone.

Next use case to clarify: record a setup-binding snapshot selected at run start
and compare it without claiming hardware truth.

### Selected Reference Marking

Supports:

- selected reference comparison;
- calibration recovery;
- handoff selection.

Why it is not a journey yet: reference labels such as last-working or notable
can start as ordinary marks on measurement records.

Next use case to clarify: mark a Measurement Record as a selected reference and
compare declared context against it.

### Environment Operation Evidence Capture

Supports:

- manual pre-run context review;
- experiment code context recovery.

Why it is not a journey yet: a bounded `uv sync` run is an operation-level
evidence source, not a user journey.

Next use case to clarify: attach bounded environment-operation review evidence
to a prepared-run or code-context use case.

## Engineering Prototype Alignment

Use this section to keep existing `src/` engineering prototypes attached to
journeys without making journeys into code owners.

### `scopecat.measurement_records`

Supports local record preparation, legacy run recording, normalized
primary-data import, durable import, storage review, and running-record
inspection use cases.

Boundary caution: it owns Measurement Records behavior and local storage
boundaries, not a universal Measurement domain model.

### `scopecat.handoff`

Supports handoff package writing/opening, receiving review, import planning,
and durable import adaptation for the portable handoff journey.

Boundary caution: the selected stored Measurement Record to package export use
case is still the main missing seam.

### `scopecat.parameter_state`

Supports parameter-state review before manual run preparation.

Boundary caution: it owns route-local parameter-state review/storage/read
behavior, not hardware apply, compatibility-file writing, or a shared
run-context schema.

### `scopecat.environment_operation`

Provides bounded environment-operation evidence for future prepared-run or
experiment-code context use cases.

Boundary caution: treat current `uv sync` support as operation evidence unless
a narrower user-facing use case promotes it.

## Update Rule

Update this map when discovery or implementation changes:

- adds, retires, or reframes a user journey;
- changes which workflows or use cases prove a journey;
- promotes a supporting workflow into a use case;
- changes which journey an engineering prototype supports.

Keep validation state, evidence posture, and implementation ownership in the
engineering validation map, discovery docs, and implementation register.
