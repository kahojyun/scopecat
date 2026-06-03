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

### JNY-001 Portable Measurement Handoff

Current journey:

- users manually copy selected legacy run data, sidecar files, notebooks,
  reports, or analysis folders;
- source identity, missing context, and transformed-versus-primary data are
  easy to lose;
- receiving users often must trust folder structure or notebook residue before
  they can inspect the data.

Transition journey:

- record legacy-backed measurement facts into local Measurement Records;
- attach reviewed normalized primary data when available;
- write a Scopecat-authored package from an accepted source;
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

- local legacy run recording: `Record` and `Bridge`;
- normalized primary-data durable import: `Bridge` and `Partial owner`;
- handoff package writing/opening: `Partial owner` for Scopecat-authored
  package artifacts;
- receiving-side review/import plan: `Review`;
- durable import from an approved package measurement: `Bridge` and
  `Partial owner`.

Deferred authority:

- legacy execution, raw historical file semantics, adapter discovery, and
  scientific validity remain outside Scopecat;
- selected stored Measurement Record to single-measurement package export is
  the next posture change to validate.

### JNY-002 Pre-Run Context Review

Current journey:

- users inspect parameter files, code folders, environment state, setup notes,
  and notebooks manually before running;
- existing systems still own hardware apply and run start;
- evidence about readiness or context is scattered.

Transition journey:

- import adapter-authored parameter state for review;
- store/read selected parameter-state facts locally;
- capture bounded environment-operation evidence when useful;
- compose prepared-run context evidence without granting run-start authority.

Target journey:

- assemble selected parameter, code, environment, and setup context into a
  reviewable pre-run package;
- show missing or risky context before run start;
- record the operator's acknowledgement, deferral, or note without taking
  hardware-control authority by default.

Ownership posture:

- adapter-authored parameter-state intake: `Bridge`;
- parameter-state storage and read view: `Partial owner`;
- source-agnostic parameter-state selection and review chain: `Review`;
- bounded environment-operation evidence: `Assist` or `Shadow`, depending on
  the later use case that consumes it.

Deferred authority:

- hardware apply, live write-back, current instrument-state truth, automatic
  run start, and shared run-context authority remain outside Scopecat.

### JNY-003 Calibration Work Continuation

Current journey:

- users recover failed fits, retry decisions, and downstream blocking from
  scattered notebook state;
- manual continuation choices are hard to inspect later.

Transition journey:

- record reviewable fit, evidence, action, and continuation summaries;
- hand accepted calibration writes into parameter-state review;
- keep execution and write-back outside Scopecat.

Target journey:

- review failed or suspicious calibration steps;
- record continuation decisions and blocked downstream work;
- optionally assist local sequential calibration only after a narrow use case
  proves the need.

Ownership posture:

- reviewable fit, action, and continuation summaries: `Record` and `Review`;
- accepted calibration write handoff to parameter-state review: candidate
  `Bridge` evidence.

Deferred authority:

- local sequential execution is not accepted yet, but may become `Assist`;
- Scopecat-decided retry, mutation, write-back, and hardware control remain
  outside Scopecat.

### JNY-004 Running Measurement Monitoring And Inspection

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

### JNY-005 Experiment Code Context Recovery And Reuse

Current journey:

- users reconstruct code context from copied folders, notebooks, helper files,
  and local path conventions;
- dirty Git state or folder names are not reliable enough for early adoption.

Transition journey:

- record explicit run/step code context with entrypoint and include policy;
- compare selected recorded-code context;
- capture bounded environment-operation evidence without executing experiment
  code.

Target journey:

- select, compare, restore, or materialize the code context associated with a
  run, calibration step, handoff, or comparison;
- keep execution and deployment authority separate until a narrower workflow
  proves the need.

Coordination role: this is a context-support journey. It should help other
journeys understand code context without becoming a generic Git, package
management, runtime, or execution journey.

Ownership posture:

- explicit run/step code-context recording: candidate `Record`;
- selected-code comparison: candidate `Review`;
- bounded `uv sync` operation evidence: `Assist` or `Shadow`.

Deferred authority:

- dependency closure, code execution, managed deployment, remote execution, and
  experiment-code runtime ownership remain outside Scopecat.

### JNY-006 Selected Reference Comparison

Current journey:

- users compare against last-working or notable references by reopening files,
  notebooks, setup notes, and memory;
- changed, missing, unverified, and not-compared facts are easy to collapse
  into vague gap language.

Transition journey:

- mark or select reference records;
- compare declared measurement, code, parameter, or setup context;
- surface objective findings without claiming domain judgment.

Target journey:

- choose a reference record or context bundle;
- review objective comparison findings across declared context;
- leave interpretation and action to the user unless a later workflow earns
  stronger authority.

Coordination role: this is a review-oriented journey that can support pre-run
review, post-run analysis, calibration continuation, monitoring review, and
handoff decisions. Do not treat every comparison input as a new standalone
journey.

Ownership posture:

- selected reference marking: candidate `Record`;
- declared context comparison: candidate `Review`.

Deferred authority:

- setup truth, user/domain judgment, rollback, and hardware or environment
  mutation remain outside Scopecat.

## Update Rule

Update this architecture when a branch changes a brownfield current journey,
transition path, target mapping, ownership posture, or deferred authority.

Do not use this file to track adoption messaging, delivery maturity,
implementation entrypoints, tests, fixtures, or task sequencing.
