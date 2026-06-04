# Brownfield Transition Architecture

## Status

Current brownfield transition architecture.

## Purpose

Describe how Scopecat bridges from current lab workflows to target product
journeys. This is a transition architecture document, not a target journey map,
adoption strategy, implementation plan, or validation map.

Use this document to separate:

- current journey: how users complete the work today;
- transition journey: the intermediate Scopecat-supported path;
- target journey: the product journey Scopecat wants to make normal;
- ownership posture: what authority has moved from legacy systems to Scopecat;
- deferred authority: what remains outside Scopecat.

## Ownership Posture Vocabulary

Ownership posture is separate from delivery maturity. It records what authority
has moved from a brownfield system to Scopecat. A use case can be an engineering
prototype while still leaving most legacy authority in place.

Use the narrowest posture that matches the accepted behavior:

- `Observe`: Scopecat reads or observes legacy/system output without changing
  it.
- `Record`: Scopecat records declared facts, references, receipts, snapshots,
  or lifecycle evidence from legacy/system behavior.
- `Review`: Scopecat provides local review, preview, comparison, or gate
  behavior while a user or legacy system remains the authority.
- `Bridge`: Scopecat explicitly adapts between a legacy/system artifact and a
  Scopecat-owned boundary.
- `Shadow`: Scopecat computes, checks, or validates beside the legacy path, but
  the legacy path remains authoritative.
- `Assist`: Scopecat helps prepare or perform user-directed work without owning
  final mutation or execution authority.
- `Partial owner`: Scopecat owns a narrow durable state, package, receipt,
  review, or mutation boundary.
- `Primary owner`: Scopecat is the primary authority for the named boundary.
- `Retired legacy path`: the old path has been explicitly replaced or stopped
  for the named boundary.

## Journey Transitions

### JNY-001 Share A Selected Measurement

Current journey:

- users manually copy selected legacy run data, sidecar files, notebooks,
  reports, or analysis folders;
- source identity, missing context, and transformed-versus-primary data are
  easy to lose;
- receiving users often must trust folder structure or notebook residue before
  they can inspect the data.

Transition journey:

- select a complete-enough local Measurement Record;
- write a Scopecat-authored package from the selected record;
- open the package read-only on the receiving side;
- import one approved package measurement into local storage.

Target journey:

- select a measurement record regardless of original system;
- preview the selected measurement and context before export;
- export a package with clear identity, primary data, and explicit missing
  context;
- preview package contents before import;
- import or reference the package through explicit user acceptance.

Ownership posture:

- selected stored-record export: `Review` and `Partial owner`;
- handoff package writing/opening: `Partial owner` for Scopecat-authored
  package artifacts;
- receiving-side review/import plan: `Review`;
- durable import from an approved package measurement: `Bridge` and
  `Partial owner`.

Deferred authority:

- legacy execution, raw historical file semantics, adapter discovery, and
  scientific validity remain outside Scopecat;
- Measurement Record creation, run recording, running updates, and post-run
  results review belong to separate journeys or workflow segments that feed
  this handoff journey.

### JNY-002 Prepare A Manual Run

Current journey:

- users inspect parameter files, code folders, environment state, setup notes,
  and notebooks manually before running;
- existing systems still own hardware apply and run start;
- evidence about readiness or context is scattered.

Transition journey:

- reuse historical parameter-state evidence as domain input only when useful;
- capture bounded environment-operation evidence when useful;
- compose prepared-run context evidence without granting run-start authority.

Target journey:

- assemble selected parameter, code, environment, setup, and prior context into
  a reviewable pre-run package;
- show missing or risky context before run start;
- record the operator's acknowledgement, deferral, or note without taking
  hardware-control authority by default;
- let a later Measurement Record reference the prepared-run receipt as context
  evidence.

Ownership posture:

- parameter-state intake, storage, selection, and review chain: retired
  prototype evidence, not an active owner;
- bounded environment-operation evidence: `Assist` or `Shadow`, depending on
  the later use case that consumes it;
- prepared-run review receipt: candidate `Record` and `Review` evidence.

Deferred authority:

- hardware apply, live write-back, current instrument-state truth, automatic
  run start, and shared run-context authority remain outside Scopecat.

### JNY-003 Recover Or Continue Calibration Work

Current journey:

- users recover failed fits, retry decisions, and downstream blocking from
  scattered notebook state;
- manual continuation choices are hard to inspect later.

Transition journey:

- record reviewable fit, evidence, action, and continuation summaries;
- preserve accepted calibration write pressure for future parameter-state
  review if a real entrypoint earns it;
- keep execution and write-back outside Scopecat.

Target journey:

- review failed or suspicious calibration steps;
- record continuation decisions and blocked downstream work;
- optionally assist local sequential calibration only after a narrow use case
  proves the need.

Ownership posture:

- reviewable fit, action, and continuation summaries: `Record` and `Review`;
- accepted calibration write handoff to parameter-state review: historical
  pressure, not an active bridge.

Deferred authority:

- local sequential execution is not accepted yet, but may become `Assist`;
- Scopecat-decided retry, mutation, write-back, and hardware control remain
  outside Scopecat.

### JNY-004 Monitor A Running Measurement

Current journey:

- users inspect long-running measurements through existing scripts, partial
  files, or live plotting tools;
- partial completeness and latest useful sweep status are ambiguous.

Transition journey:

- observe explicit lifecycle/progress events from Python measurement scripts;
- record partial data markers and local inspection state;
- review the latest useful sweep without controlling scan execution.

Target journey:

- monitor running measurements from a local review surface;
- inspect partial-but-useful data before completion;
- save selected fit or operator decisions only when the user asks.

Ownership posture:

- partial-data and progress observation: candidate `Observe` and `Record`;
- monitor review surface: candidate `Review`.

Deferred authority:

- experiment execution, scan-plan changes, automatic retune, and scheduling
  remain outside Scopecat.

### JNY-007 Record Runs

Current journey:

- users record and preserve legacy, external, notebook, or manually reviewed
  measurement facts by copying files, preserving notes, or relying on folder
  conventions;
- durable identity, source posture, and primary-data readiness are often mixed
  together.

Transition journey:

- create a local Measurement Record shell;
- record declared source identity and source posture;
- import or attach reviewed normalized primary data;
- record operator- or adapter-declared context references as receipts.

Target journey:

- turn externally produced, legacy-backed, adapter-authored, or manually
  declared run facts into a local Scopecat Measurement Record;
- keep source execution, raw historical file semantics, adapter discovery, and
  scientific validity outside Scopecat unless narrower slices earn that
  authority;
- expose the created record through local storage/catalog visibility for
  downstream workflows.

Ownership posture:

- local legacy run recording: `Record` and `Bridge`;
- normalized primary-data durable import: `Bridge` and `Partial owner`;
- recorded references: `Record`;
- local storage/catalog visibility: `Record`.

Deferred authority:

- opening, browsing, plotting, and post-run readiness review belong to
  JNY-008;
- raw legacy parsing, legacy execution, reference repair, current instrument
  truth, and scientific validity remain outside Scopecat by default.

### JNY-008 Browse And Review Completed Results

Current journey:

- users browse and reopen completed results through manually managed folders,
  notebooks, plots, reports, sidecars, and memory before deciding whether a
  measurement is ready to share or use;
- primary data, derived artifacts, plots, missing context, and operator notes
  often remain separate and hard to filter together.

Transition journey:

- review a completed Measurement Record read model and record-local receipts;
- browse, open, and filter candidate records;
- plot selected primary-data or derived-result series;
- identify missing, stale, or incomplete context;
- record operator review notes or continuation receipts;
- project a read model for downstream selection.

Target journey:

- browse, open, filter, and plot completed or near-completed measurement
  results;
- inspect primary data, context references, derived artifacts, and operator
  notes together;
- make the selected result understandable and ready for handoff, comparison,
  calibration continuation, or rerun preparation;
- keep post-run review separate from canonical source replacement.

Ownership posture:

- records browser, open, filtering, and plotter surfaces: candidate `Review`;
- operator notes and review receipts: candidate `Record`;
- read-model projection: `Review` convenience projection, not canonical storage
  authority.

Deferred authority:

- final public storage schema, manifest replacement, broad merge import,
  scientific validity, and GUI-owned review state remain outside this journey
  until narrower decisions accept them.

### JNY-009 Reproduce Or Rerun From A Reference

Current journey:

- users compare against last-working or notable references by reopening files,
  notebooks, setup notes, copied folders, and memory;
- changed, missing, unverified, and not-compared facts are easy to collapse
  into vague gap language.

Transition journey:

- mark or select reference records;
- compare declared measurement, code, parameter, or setup context;
- capture selected code-context and environment-operation evidence when useful;
- surface objective findings without claiming domain judgment.

Target journey:

- choose a reference record or context bundle;
- review objective comparison findings across declared context;
- prepare enough reviewed context to reproduce, rerun, or investigate
  differences;
- keep interpretation, setup truth, execution, and mutation with the user or a
  later workflow until stronger authority is earned.

Ownership posture:

- selected reference marking: candidate `Record`;
- declared context comparison: candidate `Review`;
- explicit run/step code-context recording: candidate `Record`;
- selected-code comparison or workspace materialization: candidate `Review` or
  `Assist`, depending on the later use case.

Deferred authority:

- setup truth, user/domain judgment, rollback, dependency closure, code
  execution, managed deployment, remote execution, and hardware or environment
  mutation remain outside Scopecat.

## Supporting Workflow Posture

The former target journey entries JNY-005 Experiment Code Context Recovery And
Reuse and JNY-006 Selected Reference Comparison are now supporting workflows.
They remain important validation owners for code-context and comparison slices,
but they should not drive standalone journey UX unless a consuming journey
proves a user-recognizable end-to-end job.

## Update Rule

Update this architecture when a branch changes a brownfield current journey,
transition path, target mapping, ownership posture, or deferred authority.

Do not use this file to track adoption messaging, delivery maturity,
implementation entrypoints, tests, fixtures, or task sequencing.
