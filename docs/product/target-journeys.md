# Target Journey Map

## Status

Current target product journey map.

## Purpose

Own Scopecat's target product-facing user journeys and the first decomposition
from discovery evidence into workflows and use cases. This is a product
planning document, not a brownfield migration document, implementation
register, scenario inventory, or engineering task plan.

## Reading Rules

Start here before promoting discovery evidence into `src/`. A discovery slice
should attach to one of these journeys, a named use case under a journey, or an
explicit evidence-only scenario or operation in the engineering validation map.

Do not create a code owner from a journey name by default. Journeys organize
product intent; implementation owners remain in the implementation register.

Do not use legacy system names as target journey names. Legacy behavior belongs
in the brownfield current-state and transition documents.

Use stable `JNY-*` IDs when referencing target journeys from brownfield,
engineering, traceability, decision, or risk documents. Journey names may change
as product language improves; IDs should not be reused.

## Experiment Lifecycle Composition

Real experiment work usually crosses several target journeys:

```text
prepare context
  -> start the run outside Scopecat
  -> monitor running measurement
  -> record or import measurement facts
  -> analyze, compare, continue calibration, or hand off selected results
```

Scopecat should acknowledge this lifecycle without claiming the whole lifecycle
as one current target journey. The current target journeys intentionally prove
smaller boundaries around review, recording, monitoring, comparison, and
handoff.

## Deferred Umbrella Journeys

### Start And Complete A Measurement

Why deferred:

- it would imply run-start authority;
- it would couple parameter apply, code execution, environment readiness,
  monitoring, result recording, failure recovery, and handoff too early;
- it would pressure Scopecat toward hardware safety, scan execution,
  scheduling, and recovery ownership before narrower workflows earn those
  boundaries.

Current slices:

- JNY-002 Pre-Run Context Review;
- JNY-005 Experiment Code Context Recovery And Reuse;
- JNY-004 Running Measurement Monitoring And Inspection;
- JNY-003 Calibration Work Continuation;
- JNY-001 Portable Measurement Handoff;
- JNY-006 Selected Reference Comparison.

Promotion condition: promote only after a narrow slice around a named use case
proves manual review, explicit run-start authority, execution boundary,
monitoring, result recording, and recovery expectations together.

## Journey Catalog

### Portable Measurement Handoff

ID: JNY-001.

Goal: move one selected measurement, with enough context to understand it, to
another computer or collaborator where it can be previewed and imported.

Primary workflows:

- local record preparation;
- selected measurement package export;
- receiving-side package review;
- durable import after explicit acceptance.

Use cases to prove:

- record externally produced measurement facts locally;
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

Validation orientation: primary active journey. Existing evidence currently
comes from legacy-backed and imported measurement records, but the target
journey is portable measurement handoff, not legacy migration itself. Evidence
covers local record preparation, selected stored-record package export, package
writing/opening, receiving review/import plan, and durable import adaptation.
The DEC-010 directory manifest package format is accepted for the current
production-slice candidate. DEC-011 keeps that package unsigned local-review
evidence: declared digest integrity is observed, but signature validation,
authenticity, sender trust, and scientific validity are not claimed. DEC-019
keeps signature/trust implementation deferred until a signed-artifact and
trust-root contract exists. Batch durable import remains a separate validation
question. DEC-012 allows generic
handoff writer inputs to package explicitly declared linked-context payloads
for review. DEC-014 allows selected stored-record export to package explicitly
declared record-local linked-context payloads without treating recorded
references as file-copy authority. DEC-013 allows multi-measurement import
planning, while durable import remains one-record-at-a-time. DEC-015 allows
selected stored-record batch package export without adding batch durable import.
DEC-016 keeps linked-context payload import deferred until Measurement Records
has an accepted context artifact storage contract. DEC-017 keeps batch durable
import deferred until a destination and partial-success contract exists.
DEC-018 defines receiving review state as a derived local projection without
accepting a persisted GUI state store.

Source evidence:

- [`selected-run-handoff.md`](../discovery/problem-briefs/selected-run-handoff.md);
- [`measurement-record-boundary.md`](../discovery/problem-briefs/measurement-record-boundary.md).

### Pre-Run Context Review

ID: JNY-002.

Goal: review selected parameter, code, environment, and setup context before a
manual run without giving Scopecat execution or hardware-control authority.

Primary workflows:

- parameter-state intake and review;
- context selection;
- prepared-run review;
- optional environment-operation evidence;
- operator acknowledgement or deferral.

Use cases to prove:

- import and review adapter-authored parameter state;
- store and read reviewed parameter state;
- select source-agnostic parameter state for run preparation;
- consume parameter-state facts in a prepared-run review chain;
- capture bounded environment-operation evidence;
- record code context for a run or step;
- record operator acknowledgement, deferral, or note;
- later add setup-binding snapshot selection.

Supporting capabilities:

- Parameter State Review;
- Experiment Code Context;
- Environment Operation;
- Measurement Records context links;
- setup-binding candidate workflow.

Validation orientation: parameter-state review has live engineering prototype
coverage. Prepared-run context and acknowledgement remain scenario evidence
without a live route owner. Environment operation is operation evidence for
later readiness/context use, not a standalone journey.

Source evidence:

- [`parameter-state-management.md`](../discovery/problem-briefs/parameter-state-management.md);
- [`experiment-code-recording.md`](../discovery/problem-briefs/experiment-code-recording.md);
- [`setup-binding.md`](../discovery/problem-briefs/setup-binding.md).

### Calibration Work Continuation

ID: JNY-003.

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

Validation orientation: candidate feature area with discovery and
implementation-candidate evidence. It should not become a live route owner
until a narrow calibration continuation use case has acceptance criteria.

Source evidence:

- [`calibration-work-continuation.md`](../discovery/problem-briefs/calibration-work-continuation.md);
- [`calibration-fit-validation-dataset.md`](../discovery/problem-briefs/calibration-fit-validation-dataset.md).

### Running Measurement Monitoring And Inspection

ID: JNY-004.

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

Validation orientation: discovery and validation-question stage. No live
product capability owner yet beyond related Measurement Records inspection
evidence.

Source evidence:

- [`running-measurement-inspection.md`](../discovery/problem-briefs/running-measurement-inspection.md).

### Experiment Code Context Recovery And Reuse

ID: JNY-005.

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

Validation orientation: discovery and implementation-candidate evidence.
Environment Operation currently provides operation evidence for bounded
`uv sync`, not a full code-context or runtime-readiness journey.
This journey supports other journeys by making code context understandable; it
does not own Git replacement, package management, deployment, runtime, or
experiment execution by default.

Source evidence:

- [`experiment-code-recording.md`](../discovery/problem-briefs/experiment-code-recording.md).

### Selected Reference Comparison

ID: JNY-006.

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

Validation orientation: discovery evidence. The first credible use case is
comparison over declared context, not a universal setup truth or judgment
engine.
This is a review-oriented journey that can support pre-run, post-run,
calibration, monitoring, and handoff decisions without turning every comparison
input into a separate target journey.

Source evidence:

- [`selected-reference-comparison.md`](../discovery/problem-briefs/selected-reference-comparison.md).

## Supporting Workflow Candidates

### Setup Binding Snapshot

Supports:

- pre-run context review;
- selected reference comparison;
- portable handoff context.

Why it is not a journey yet: the evidence shows a reusable context family, but
no complete user journey starts and ends with setup binding alone.

Source evidence:

- [`setup-binding.md`](../discovery/problem-briefs/setup-binding.md).

## Update Rule

Update this map when discovery or implementation changes:

- adds, renames, or removes a target user journey;
- changes a journey goal, primary workflows, or use cases to prove;
- promotes a supporting workflow candidate into a journey;
- changes which journey an engineering prototype supports.

Keep validation state, evidence posture, brownfield migration state, and
implementation ownership in their narrower owner documents.
