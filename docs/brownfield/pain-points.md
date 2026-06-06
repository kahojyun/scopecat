# Brownfield Pain Points

## Status

Current brownfield pain-point inventory.

## Purpose

Track concrete workflow friction in the existing lab environment and the
Scopecat opportunity each friction creates.

Use this file when choosing where brownfield migration should start or when a
journey, capability, risk, or validation row needs the underlying user pain.
Use [`current-state-assessment.md`](current-state-assessment.md) for as-is
workflow and artifact patterns, [`../product/target-journeys.md`](../product/target-journeys.md)
for canonical `JNY-*` and `UC-*` ownership, and
[`../engineering/workflow-validation-map.md`](../engineering/workflow-validation-map.md)
for validation evidence.

## Reading Rules

- `BR-PAIN-*` IDs are stable references for brownfield pain. Titles may change
  for clarity.
- Rows start from current-state work patterns, not from capability names,
  solution areas, or historical exploration categories.
- Pain rows describe user friction and migration opportunity; they do not own
  validation evidence, roadmap sequence, implementation entrypoints, active
  tasks, scope boundaries, or non-claims.
- Use the `Boundary / Risk Owner` pointer to find authority limits, deferred
  ownership, and durable non-claims. Do not copy those limits into pain rows.

## Pain Points

| ID | Pain Point | Primary Current Work Pattern | Also Appears In | Current Friction | User Impact | Current Workaround | Scopecat Opportunity | Related Owners | Boundary / Risk Owner |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BR-PAIN-001 | Run evidence is scattered across storage, sidecars, notebooks, and folders. | Recording runs | Reviewing completed results; selecting measurements for sharing. | Experiment scripts create storage rows and numeric IDs while notebooks, generated companions, parameter snapshots, CSV/NPZ/JSON files, and analysis artifacts accumulate nearby. | Users cannot reliably explain source identity, primary data, transformed data, or context completeness from one durable handle. | Infer meaning from filenames, folder adjacency, notebook cells, copied snapshots, and memory. | Measurement Records can give externally produced runs local identity, source posture, normalized primary-data state, declared references, and explicit ambiguity. | JNY-007, JNY-008; UC-001, UC-002, UC-CAND-007; CAP-001 | [`measurement-records-storage.md`](../engineering/prototype-boundaries/measurement-records-storage.md), ADR-0002, ADR-0003, BR-RISK-002, BR-RISK-003 |
| BR-PAIN-002 | Selected results do not travel with enough identity, completeness, or missing-context visibility. | Selecting measurements for sharing | Reviewing completed results; transferring work between computers. | Users move run data, derived arrays, notebooks, reports, helper files, and selected-ID notes as ad hoc folders or shared bundles. | Receivers must reconstruct identity, primary-versus-derived data, source completeness, and missing context before useful inspection. | Copy folders, attach notes, preserve nearby files, and explain gaps manually. | Handoff Packages can export selected Measurement Records, preserve source identity, make missing context visible, and separate read-only open from accepted import. | JNY-001; UC-003, UC-004, UC-006, JNY-001-SMOKE; CAP-001, CAP-002 | [`handoff.md`](../engineering/prototype-boundaries/handoff.md), [`handoff-durable-import-storage.md`](../engineering/prototype-boundaries/handoff-durable-import-storage.md), ADR-0007, ADR-0008, BR-RISK-004, BR-RISK-010 |
| BR-PAIN-003 | Pre-run context and readiness are not reviewable in one place. | Checking context before a run | Reconstructing a reference or rerun; maintaining parameter and setup files. | Users inspect parameter files, setup notes, wiring spreadsheets, code folders, environment state, services, and notebooks before starting a run elsewhere. | Readiness evidence and chosen context remain scattered, so later run interpretation depends on manual memory. | Follow local check habits, keep notes, inspect files by hand, and start the run outside Scopecat. | Prepared-run review can compose declared context, bounded readiness findings, acknowledgement or deferral, and later Measurement Record links. | JNY-002; UC-CAND-002, UC-CAND-003, UC-CAND-006; CAP-001, CAP-003, CAP-004, CAP-005 | [`transition-architecture.md`](transition-architecture.md), ADR-0004, BR-RISK-001, BR-RISK-008, BR-RISK-009 |
| BR-PAIN-004 | Parameter, setup, registry, and generated context drift without trusted point-in-time selection. | Maintaining parameter and setup files | Checking context before a run; reconstructing a reference or rerun. | Active JSON, copied seeds, dated variants, generated line/chip companions, wiring workbooks, registry files, notes, labels, and run snapshots coexist. | Users struggle to know which state was trusted, incomplete, selected, changed, or relevant to a run. | Inspect copies, compare diffs manually, preserve dated variants, and rely on operator notes. | Scopecat can preserve point-in-time parameter/setup context, reviewable diffs, trust/readiness labels, measurement links, and attention-worthy changes while keeping state families separate. | JNY-002, JNY-009; UC-CAND-002, UC-CAND-006; CAP-003, CAP-001 context links | [`transition-architecture.md`](transition-architecture.md), ADR-0004, BR-RISK-001, BR-RISK-005 |
| BR-PAIN-005 | Code context behind a run is hard to identify later. | Reconstructing code context | Checking context before a run; reconstructing a reference or rerun; selecting measurements for sharing. | Notebooks, helper modules, copied folders, dirty or nested repositories, generated companions, private imports, and local runtime assumptions shape runs and analysis. | Users cannot reliably explain which entrypoint, source root, helper files, or workspace state mattered for a run or review artifact. | Remember entrypoints, inspect Git opportunistically, copy folders, and preserve helper files manually. | Experiment Code Context can record explicit root/source reference, entrypoint, include policy, stripped notebook source, declared context links, and later managed-code selection pressure. | JNY-002, JNY-009; UC-CAND-003; CAP-005 | [`managed-experiment-code-posture.md`](../product/managed-experiment-code-posture.md), ADR-0005, BR-RISK-009, [`transition-architecture.md`](transition-architecture.md) |
| BR-PAIN-006 | Running and partial measurement lifecycle is ambiguous. | Inspecting running measurements | Reviewing completed results; continuing calibration work. | Long-running measurements expose rows, progress, partial data, stop/interruption state, and temporary fit previews through scripts, live graphers, files, or notebook output. | Users cannot tell from durable evidence whether a run is useful, complete enough, interrupted, recoverable, or invalid. | Inspect live surfaces, notebooks, and partial files manually, then decide whether to stop, continue, or recover. | A running monitor can consume explicit lifecycle, progress, completeness, and partial-data events without taking scan control. | JNY-004; UC-CAND-004; CAP-006, CAP-001 | [`transition-architecture.md`](transition-architecture.md), ADR-0004, BR-RISK-001 |
| BR-PAIN-007 | Calibration recovery loses fit decisions, proposed writes, suspicious cases, and continuation intent. | Continuing calibration work | Maintaining parameter and setup files; inspecting running measurements. | Multi-step calibration mixes sequential scans, failed or suspicious fits, manual review, proposed writes, continuation choices, and downstream blocking in notebooks and local code. | Users lose progress, proposed next actions, and cases that could improve later fit-code review. | Recover from notebook state, rerun helper code, preserve ad hoc notes, and manually carry continuation choices forward. | Calibration continuation review can record user-authored steps, review state, fit outcomes, candidate fit cases, continuation actions, and handoff to parameter or measurement context. | JNY-003; UC-CAND-005; CAND-001, CAP-003, CAP-001 context links | [`transition-architecture.md`](transition-architecture.md), ADR-0004, BR-RISK-001, BR-RISK-005 |
| BR-PAIN-008 | Completed-result review is folder and notebook archaeology. | Reviewing completed results | Selecting measurements for sharing; reconstructing a reference or rerun. | Users reopen stored rows or numeric IDs, browse folders, inspect notebooks, plot series, review reports, and track selected results outside a record browser. | Users struggle to decide what is ready for handoff, comparison, calibration continuation, or rerun preparation. | Reopen data manually, inspect notebooks and reports, create plots, and keep readiness notes outside durable record state. | Post-run review can browse records, distinguish primary data from derived artifacts, expose missing context, and record readiness notes before downstream use. | JNY-008; UC-CAND-007; CAP-001, CAP-002, CAP-005 | [`measurement-records-storage.md`](../engineering/prototype-boundaries/measurement-records-storage.md), BR-RISK-003, BR-RISK-010 |
| BR-PAIN-009 | Reference and rerun comparison collapses different kinds of context difference. | Reconstructing a reference or rerun | Checking context before a run; reviewing completed results; reconstructing code context. | Users compare against last-working or notable references by reopening records, files, code folders, setup notes, parameters, generated artifacts, and environment evidence. | Changed, missing, unverified, redacted, unlinked, same-observed, and not-compared facts collapse into vague gap language. | Reopen old artifacts, compare context manually, and rely on user/domain judgment for interpretation. | Selected-reference comparison can report declared context findings against a user-selected reference while leaving interpretation to users. | JNY-009; UC-CAND-006; CAP-001, CAP-003, CAP-005 | [`transition-architecture.md`](transition-architecture.md), ADR-0005, BR-RISK-005, BR-RISK-009 |

## Update Rule

Update this inventory when a new current-state workflow pain changes migration
opportunity, when a pain point is retired by production behavior, or when a
row needs a clearer relation to journey, capability, boundary, risk, or
validation owners.

Do not use this file as a roadmap, validation map, implementation register,
architecture decision record, or active task queue.
