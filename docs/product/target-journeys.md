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
engineering, traceability, decision, or risk documents. Journey names may
change as product language improves; IDs should not be reused. When an older
entry is demoted from target journey to supporting workflow, keep its former ID
documented as retired instead of assigning it to a different journey.

## Journey Selection Rule

Treat a target journey as a user-recognizable end-to-end job, not as a named
context family or implementation capability. A journey should have:

- an actor-facing trigger;
- a clear done state or review outcome;
- a product surface that composes more than one route-local capability or
  authority boundary;
- brownfield migration pressure that is hard to solve as a single capability
  use case.

Workflow segments and capability use cases may support multiple journeys
without becoming journeys themselves.

## Experiment Lifecycle Composition

Real experiment work usually crosses several target journeys:

```text
prepare a manual run
  -> start the run outside Scopecat
  -> monitor running measurement
  -> record run facts
  -> browse and review completed results
  -> share selected results, continue calibration, or reproduce from reference
```

Scopecat should acknowledge this lifecycle without claiming the whole lifecycle
as one current target journey. The current target journeys intentionally prove
smaller boundaries around preparation, recording, monitoring, review,
handoff, calibration continuation, and reproduction.

## Deferred Umbrella Journeys

### Start And Complete A Measurement

Why deferred:

- it would imply run-start authority;
- it would couple parameter apply, code execution, environment readiness,
  monitoring, result recording, failure recovery, final review, and handoff too
  early;
- it would pressure Scopecat toward hardware safety, scan execution,
  scheduling, and recovery ownership before narrower workflows earn those
  boundaries.

Current slices:

- JNY-002 Prepare A Manual Run;
- JNY-004 Monitor A Running Measurement;
- JNY-007 Record Runs;
- JNY-008 Browse And Review Completed Results;
- JNY-001 Share A Selected Measurement;
- JNY-003 Recover Or Continue Calibration Work;
- JNY-009 Reproduce Or Rerun From A Reference.

Promotion condition: promote only after a narrow slice around a named use case
proves manual review, explicit run-start authority, execution boundary,
monitoring, result recording, post-run review, and recovery expectations
together.

## Journey Catalog

### Share A Selected Measurement

ID: JNY-001.

Goal: select one Measurement Record that is complete enough for handoff, export
it to a reviewable package, and let a receiving user preview and import it
explicitly.

Primary workflows:

- selected Measurement Record review before export;
- selected measurement package export;
- receiving-side package review;
- durable import after explicit acceptance.

Use cases to prove:

- export one selected stored Measurement Record to a handoff package;
- open a package read-only;
- build a non-mutating import plan;
- import one approved package measurement into durable local storage;
- keep receiving review, package integrity observation, and durable import
  separate from sender trust, authenticity, and scientific validity.

Supporting capabilities:

- Measurement Records;
- Handoff Packages;
- Experiment Code Context later;
- Parameter State Review later.

Validation orientation: primary active journey. Existing evidence includes the
input-side Measurement Records work needed to prove handoff, but the target
journey is sharing a selected measurement, not owning the whole Measurement
Records lifecycle. Record creation, run recording, running updates, and
post-run results review are separate journeys or workflow segments that feed
this journey.

The DEC-010 directory manifest package format is accepted for the current
production vertical slice candidate. DEC-011 keeps that package as local
declared-integrity evidence: digest integrity is observed, but external
authenticity, sender trust, and scientific validity are not claimed.
DEC-021 accepts safe zip materialization into the DEC-010 package of record,
and DEC-024 accepts safe zip creation from the DEC-010 package of record.
Archive-backed durable import remains a separate validation question. Batch
durable import remains a separate validation question. DEC-012 allows generic
handoff writer inputs to package explicitly declared linked-context payloads
for review. DEC-014 allows selected stored-record export to package explicitly
declared record-local linked-context payloads without treating recorded
references as file-copy authority. DEC-013 allows multi-measurement import
planning, while durable import remains one-record-at-a-time. DEC-015 allows
selected stored-record batch package export without adding batch durable
import. DEC-016 keeps linked-context payload import deferred until Measurement
Records has an accepted context artifact storage contract. DEC-017 keeps batch
durable import deferred until a destination and partial-success contract
exists. GUI-owned receiving review state remains unaccepted. DEC-025 keeps the
JNY-001 handoff vertical slice source-storage-read-only on export and
new-record-only on durable import; existing-record update, merge import,
manifest replacement, and final storage schema publication remain separate
validation questions.

Source evidence:

- [`selected-run-handoff.md`](../discovery/problem-briefs/selected-run-handoff.md);
- [`measurement-record-boundary.md`](../discovery/problem-briefs/measurement-record-boundary.md).

### Prepare A Manual Run

ID: JNY-002.

Goal: review selected parameter, code, environment, setup, and prior context
before a manual run without giving Scopecat execution, run-start, or
hardware-control authority.

Primary workflows:

- parameter/context intake and review;
- context selection;
- prepared-run review;
- optional environment-operation evidence;
- operator acknowledgement or deferral.

Use cases to prove:

- review selected parameter/context facts for run preparation;
- capture bounded environment-operation evidence;
- record code context for a run or step;
- record operator acknowledgement, deferral, or note;
- record a prepared-run review receipt that a later Measurement Record can
  reference as context evidence;
- later add setup-binding snapshot selection.

Supporting capabilities:

- Parameter State Review;
- Experiment Code Context;
- Environment Operation;
- Measurement Records context links;
- setup-binding candidate workflow.

Validation orientation: the former parameter-state prototype is retired
historical evidence, not active implementation coverage. Prepared-run context
and acknowledgement remain scenario evidence without a live route owner.
Environment operation is operation evidence for later readiness/context use, not
a standalone journey. This journey should compose review-ready summaries from
supporting capabilities; it should not own all parameter, code, environment, or
setup management UX.

Source evidence:

- [`parameter-state-management.md`](../discovery/problem-briefs/parameter-state-management.md);
- [`experiment-code-recording.md`](../discovery/problem-briefs/experiment-code-recording.md);
- [`setup-binding.md`](../discovery/problem-briefs/setup-binding.md).

### Recover Or Continue Calibration Work

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

- review a failed or suspicious calibration fit;
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

### Monitor A Running Measurement

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

### Record Runs

ID: JNY-007.

Goal: record existing, external, legacy-backed, adapter-authored, or manually
declared run facts as a local Scopecat Measurement Record without replacing the
system that produced the measurement.

Primary workflows:

- create a local Measurement Record shell;
- record source identity and source posture;
- import or attach reviewed normalized primary data;
- record context references supplied by the operator or adapter;
- write the created record to the local Measurement Records store for
  downstream journeys;
- keep raw source execution, parsing, and scientific validity outside
  Scopecat unless a narrower adapter slice earns that authority.

Use cases to prove:

- record existing or externally produced measurement facts locally;
- attach reviewed normalized primary data;
- import reviewed normalized primary data into a new durable record;
- record parameter, setup, code, artifact, and evidence references as
  record-local receipts;
- expose the created record to the local Measurement Records store.

Supporting capabilities:

- Measurement Records;
- adapter-authored import and review surfaces;
- Handoff Packages later;
- Parameter State Review later;
- Experiment Code Context later.

Validation orientation: this target journey separates the input side of
Measurement Records from JNY-001 handoff. Current evidence exists as
engineering prototype work under Measurement Records and as the input
scaffolding used by JNY-001. The open question is not whether JNY-007 belongs
in the target catalog; it is which first user-facing route or use case should
own recording beyond handoff support. Opening, browsing, plotting, and post-run
readiness review belong to JNY-008.

Source evidence:

- [`measurement-record-boundary.md`](../discovery/problem-briefs/measurement-record-boundary.md);
- [`selected-run-handoff.md`](../discovery/problem-briefs/selected-run-handoff.md).

### Browse And Review Completed Results

ID: JNY-008.

Goal: browse, filter, plot, and review completed or near-completed measurement
results so the user can find and open relevant records, inspect primary data and
derived artifacts, and decide whether a result is ready for handoff, comparison,
calibration continuation, or rerun preparation.

Primary workflows:

- records browser and filtering;
- completed-record open;
- primary-data and derived-artifact inspection;
- result plotting and exploratory review;
- context completeness and readiness review;
- operator review receipt or readiness note.

Use cases to prove:

- find relevant completed or near-completed Measurement Records;
- open primary data, derived artifacts, reports, notes, and context references;
- plot selected result series or ranges before choosing what matters;
- identify missing or stale context;
- record an operator note, acknowledgement, or continuation decision;
- surface whether the result is ready for handoff or needs more review;
- keep browsing, plotting, and review separate from canonical source
  replacement.

Supporting capabilities:

- Measurement Records;
- records browser and plotter candidates;
- selected reference comparison workflow;
- Experiment Code Context;
- Handoff Packages later;
- Calibration Continuation Review later.

Validation orientation: this target journey is the user-facing post-run result
review hypothesis behind records browser and plotter pressure. Current JNY-001
evidence includes selected-record export and read-model freshness checks, but
post-run browsing, plotting, and readiness review should not remain hidden
inside handoff. The open question is which first route or use case should own
the live records browser, plotter, and readiness-review behavior.

Source evidence:

- [`measurement-record-boundary.md`](../discovery/problem-briefs/measurement-record-boundary.md);
- [`selected-reference-comparison.md`](../discovery/problem-briefs/selected-reference-comparison.md).

### Reproduce Or Rerun From A Reference

ID: JNY-009.

Goal: start from a known-good or otherwise selected reference, compare the
current context against it, and prepare enough reviewed context to reproduce,
rerun, or investigate differences without claiming setup truth or execution
authority.

Primary workflows:

- reference selection;
- declared measurement/context comparison;
- selected code-context comparison;
- workspace or rerun preparation;
- finding review.

Use cases to prove:

- mark or select a reference record;
- compare declared measurement/context facts;
- compare selected code context;
- prepare a selected code workspace for rerun;
- classify changed, missing, unverified, redacted, unlinked, same-observed, and
  not-compared facts;
- leave interpretation and action to the user unless a later workflow earns
  stronger authority.

Supporting capabilities:

- Measurement Records;
- Experiment Code Context;
- Environment Operation;
- Parameter State Review;
- setup-binding candidate workflow.

Validation orientation: this journey composes the former code-context and
selected-reference journey entries into a more user-recognizable brownfield
job. Experiment Code Context and Selected Reference Comparison remain
supporting workflows until a rerun/reproduction use case has acceptance
criteria and a clear route owner.

Source evidence:

- [`experiment-code-recording.md`](../discovery/problem-briefs/experiment-code-recording.md);
- [`selected-reference-comparison.md`](../discovery/problem-briefs/selected-reference-comparison.md).

## Supporting Workflow Candidates

### Experiment Code Context Recovery And Reuse

Former target journey ID: JNY-005, retired from the target journey catalog.

Supports:

- Prepare A Manual Run;
- Share A Selected Measurement;
- Recover Or Continue Calibration Work;
- Reproduce Or Rerun From A Reference.

Why it is not a journey now: the evidence shows a reusable context family, but
code context alone is not yet a user-recognizable end-to-end brownfield job.
Its first promoted step should be chosen by a consuming journey: record,
compare, materialize, observe editable folder, prepare rerun, or GUI review.

Source evidence:

- [`experiment-code-recording.md`](../discovery/problem-briefs/experiment-code-recording.md).

### Selected Reference Comparison

Former target journey ID: JNY-006, retired from the target journey catalog.

Supports:

- Prepare A Manual Run;
- Browse And Review Completed Results;
- Recover Or Continue Calibration Work;
- Reproduce Or Rerun From A Reference;
- Share A Selected Measurement later.

Why it is not a journey now: selected-reference comparison is a reusable review
workflow that can support several journeys. It should become a journey only if
users treat comparison itself as an independent job with a stable trigger,
result, product surface, and acceptance criteria.

Source evidence:

- [`selected-reference-comparison.md`](../discovery/problem-briefs/selected-reference-comparison.md).

### Setup Binding Snapshot

Supports:

- Prepare A Manual Run;
- Reproduce Or Rerun From A Reference;
- Share A Selected Measurement context later.

Why it is not a journey now: the evidence shows a reusable context family, but
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
