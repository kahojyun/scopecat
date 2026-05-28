# Calibration Fit Validation Dataset Validation Plan

## Status

Validation-planning draft.

This is not an ADR, fitting framework, score contract, analysis-result model,
dataset registry design, package/export format, GUI design, runner design,
retry policy, write-back policy, remote-execution design, or hardware-control
decision. It defines a first narrow validation question for fit-failure
recovery and lab-internal validation dataset curation.

Owning problem brief:
[`brief`](../../problem-briefs/calibration-fit-validation-dataset.md).

Related evidence:
`EV-005`, `EV-024`, `EV-047`, and `EV-051` in
[`../evidence/evidence-register.md`](../../../evidence/evidence-register.md).

Artifact posture: planned fixture inputs and expected outputs should be
`internal_validation_summary` repository-safe artifacts, not portable/public
export datasets. A future dataset artifact generated for lab sharing, carried
away, exported outside the repository or local workspace, or materialized as a
package must open an explicit sharing or portable/export boundary.

## Validation Question

Can Scopecat represent user-owned fit incidents as a small candidate queue that
helps users choose recovery actions and optionally promote selected cases into
a lab-internal validation dataset, without Scopecat executing fits, defining
fit quality, deciding remeasurement, applying parameter writes, or owning a
dataset registry?

This slice should validate the workflow boundary between:

- **recovery:** keep the experiment moving by remeasuring, refitting with
  adjusted ROI or initial guesses, accepting after review, or skipping;
- **curation:** preserve selected fit incidents as validation cases for later
  user-code improvement;
- **replay intent:** record enough context for a future user-owned replay
  harness to test improved fit code against prior cases.

It should stay calibration-specific until another slice pressures the same
concepts. General analysis datasets, public benchmark datasets, and model
evaluation infrastructure are not earned by this first slice.

## User Job

When a fit fails or looks suspicious, the user wants to avoid losing the case
while deciding what to do next.

The user needs to see:

- what data or measurement the fit incident came from;
- whether the incident is currently a no-signal case, signal-but-fit-failed
  case, accepted-after-review case, or other user-labeled state;
- what fit attempt, user code reference, config, ROI, initial guess, output, or
  failure message is known;
- what immediate recovery actions are available, such as remeasure, adjust
  ROI, adjust initial guess, refit, skip, or accept after review;
- whether the user selected the incident for validation-dataset inclusion;
- what minimal replay context would be available later;
- which details remain missing, unverified, local-only, or not portable.

## First Fixture Concept

Start with one synthetic public-safe fixture. It should be hand-authored and
repository-safe. It should not read source data, execute user code, run a fit,
open notebooks, inspect local sample paths, or perform filesystem mutation.

The fixture should contain three fit incidents:

- one **no-signal** incident where the next likely action is parameter
  adjustment and remeasurement, and dataset promotion is not selected;
- one **signal-visible fit failure** where the user tried or requested ROI or
  initial-guess adjustment and selected the case for validation-dataset
  inclusion;
- one **accepted-after-review** incident where a suspicious score or warning was
  reviewed, accepted for current work, and also selected as a regression case.

Each incident should use synthetic identifiers and small declared facts:

- measurement record reference;
- calibration target and fit family label;
- declared preview metadata or plot/data-shape hint;
- user-owned fit attempt reference;
- user code reference, such as a managed code version or recorded entrypoint;
- fit config facts, such as ROI label, initial-guess profile, or bounds label;
- user-provided outcome labels;
- recovery actions available or chosen;
- dataset inclusion state;
- missing context or non-portable context findings.

The fixture should not include real raw data, real paths, real hostnames, real
sample labels, private identifiers, or sensitive lab values.

## Candidate Summary Shape

If the fixture earns a code-shaped experiment, the first candidate should be a
side-effect-free projection:

```text
FitValidationDatasetInput
  -> build_fit_validation_dataset_summary(...)
  -> FitValidationDatasetSummary
```

The summary may include:

- `queue`: ordered fit incidents with state, labels, source references,
  recovery choices, and dataset-selection status;
- `recovery_actions`: immediate user choices grouped by incident, without
  Scopecat choosing one;
- `dataset_candidates`: selected incidents projected into minimal validation
  case records;
- `replay_context`: user-code reference, fit config, measurement/data
  reference, expected regression behavior, and missing prerequisites;
- `dataset_draft`: lab-internal validation dataset identity, selected cases,
  withheld cases, and readiness findings;
- `attention`: missing source, missing code reference, unavailable preview,
  no-signal remeasurement pressure, ambiguous ROI/config, non-portable context,
  or selected case missing replay context;
- `boundary`: summary posture and explicit non-claims around fit execution,
  scoring, parameter mutation, hardware control, and public export.

Normal states should not become warnings. For example, a user choosing
`no_signal_remeasure` is ordinary recovery state. Warnings should be reserved
for attention-worthy consequences, such as a selected dataset case that lacks a
data reference or fit-code reference.

## Minimal Validation Case Record

The first validation case record should be intentionally small:

```text
validation_case_id
source_measurement_ref
calibration_target
fit_family
incident_labels
user_fit_attempt_ref
user_code_ref
fit_config_ref
review_note_ref
expected_replay_behavior
```

The record should preserve user intent, not define fit correctness. Examples of
`expected_replay_behavior` are:

- improved code should complete without exception;
- improved code should tolerate this ROI shape;
- improved code should report no-signal rather than a misleading parameter;
- improved code should keep this accepted-after-review result stable enough for
  user review.

These are user-owned expectations. Scopecat records them so a later user-owned
replay harness can consume them.

## Boundary

Do not include these in the first slice:

- fitting implementation;
- fit model selection;
- Scopecat-defined score, pass/fail threshold, or scientific conclusion;
- automatic ROI selection, outlier rejection, or initial-guess generation;
- automatic remeasurement, retry, retune, or optimization;
- Scopecat-decided parameter write-back;
- hardware-control behavior;
- local executor or notebook execution;
- dataset registry service;
- portable/public dataset package;
- GUI implementation;
- general-purpose ML or analysis dataset infrastructure.

Fit attempts, scores, thresholds, ROI edits, initial guesses, and replay
expectations may appear only as user-owned or fixture-declared facts.

## Relationship To Existing Slices

This slice should reuse pressure from earlier work without expanding their
contracts:

- calibration work continuation owns step/review/resume pressure, but not
  validation dataset curation;
- running measurement inspection may expose temporary fit previews, but they
  become durable only when the user saves an incident or decision;
- handoff package surfaces reserve read-only analysis/fit extension points, but
  they do not execute fits or own analysis write-back;
- selected-reference comparison keeps raw-data and fit-quality comparison out
  of scope, which this slice should respect by treating replay as future
  user-owned work.

## Done For This Planning Stage

This plan is sufficient when the next task can be stated as:

- create one small repository-safe fit-incident fixture;
- define an expected summary with candidate queue, recovery choices, and
  dataset-candidate projection;
- include no-signal remeasurement, signal-visible refit, and
  accepted-after-review cases;
- prove selected cases can carry enough user-owned replay context without
  Scopecat fitting or scoring;
- keep lab-internal dataset draft posture separate from portable/export
  packaging.

Do not promote a dataset registry, fitting API, score model, GUI, runner,
write-back path, or hardware-control behavior from this slice alone.
