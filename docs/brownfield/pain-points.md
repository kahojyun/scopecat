# Brownfield Pain Points

## Status

Current brownfield pain-point inventory.

## Purpose

Track concrete workflow friction in the existing lab environment and the
Scopecat opportunity each friction creates.

Use this file when choosing where brownfield migration should start or when a
journey, capability, risk, or validation row needs the underlying user pain.
Use [`current-state-assessment.md`](current-state-assessment.md) for as-is
workflow and artifact patterns,
[`../product/target-journeys.md`](../product/target-journeys.md) for canonical
`JNY-*` and `UC-*` ownership, and
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
- Link to the per-ID headings below when referencing a specific pain point.

## Pain Point Index

| ID | Pain Point | Primary Current Work Pattern | Related Product Owners |
| --- | --- | --- | --- |
| [BR-PAIN-001](#br-pain-001) | Run evidence is scattered across storage, sidecars, notebooks, and folders. | Recording runs | JNY-007, JNY-008; UC-001, UC-002, UC-CAND-007; CAP-001 |
| [BR-PAIN-002](#br-pain-002) | Selected results do not travel with enough identity, completeness, or missing-context visibility. | Selecting measurements for sharing | JNY-001; UC-003, UC-004, UC-006, JNY-001-SMOKE; CAP-001, CAP-002 |
| [BR-PAIN-003](#br-pain-003) | Pre-run context and readiness are not reviewable in one place. | Checking context before a run | JNY-002; UC-CAND-002, UC-CAND-003, UC-CAND-006; CAP-001, CAP-003, CAP-004, CAP-005 |
| [BR-PAIN-004](#br-pain-004) | Parameter, setup, registry, and generated context drift without trusted point-in-time selection. | Maintaining parameter and setup files | JNY-002, JNY-009; UC-CAND-002, UC-CAND-006; CAP-003, CAP-001 context links |
| [BR-PAIN-005](#br-pain-005) | Code context behind a run is hard to identify later. | Reconstructing code context | JNY-002, JNY-009; UC-CAND-003; CAP-005 |
| [BR-PAIN-006](#br-pain-006) | Running and partial measurement lifecycle is ambiguous. | Inspecting running measurements | JNY-004; UC-CAND-004; CAP-006, CAP-001 |
| [BR-PAIN-007](#br-pain-007) | Calibration recovery loses fit decisions, proposed writes, suspicious cases, and continuation intent. | Continuing calibration work | JNY-003; UC-CAND-005; CAND-001, CAP-003, CAP-001 context links |
| [BR-PAIN-008](#br-pain-008) | Completed-result review is folder and notebook archaeology. | Reviewing completed results | JNY-008; UC-CAND-007; CAP-001, CAP-002, CAP-005 |
| [BR-PAIN-009](#br-pain-009) | Reference and rerun comparison collapses different kinds of context difference. | Reconstructing a reference or rerun | JNY-009; UC-CAND-006; CAP-001, CAP-003, CAP-005 |
| [BR-PAIN-010](#br-pain-010) | Experiment/tool code versions are hard to align across measurement computers. | Moving or synchronizing experiment code between measurement computers | JNY-002, JNY-009; UC-CAND-003; CAP-005 |
| [BR-PAIN-011](#br-pain-011) | Primary-data shape is implicit or table-constrained. | Recording and reviewing shaped measurement data | JNY-007, JNY-004, JNY-008; UC-CAND-004, UC-CAND-007; CAP-001, CAP-006 |

## Pain Point Details

### BR-PAIN-001

**Pain Point:** Run evidence is scattered across storage, sidecars, notebooks,
and folders.

**Primary Current Work Pattern:** Recording runs.

**Also Appears In:** Reviewing completed results; selecting measurements for
sharing.

**Current Friction:** Experiment scripts create storage rows and numeric IDs
while notebooks, generated companions, parameter snapshots, CSV/NPZ/JSON files,
and analysis artifacts accumulate nearby.

**User Impact:** Users cannot reliably explain source identity, primary data,
transformed data, or context completeness from one durable handle.

**Current Workaround:** Infer meaning from filenames, folder adjacency,
notebook cells, copied snapshots, and memory.

**Scopecat Opportunity:** Measurement Records can give externally produced runs
local identity, source posture, normalized primary-data state, declared
references, and explicit ambiguity.

**Related Product Owners:** JNY-007, JNY-008; UC-001, UC-002, UC-CAND-007;
CAP-001.

**Boundary / Risk Owner:**
[`measurement-records-storage.md`](../engineering/prototype-boundaries/measurement-records-storage.md),
ADR-0002, ADR-0003, BR-RISK-002, BR-RISK-003.

### BR-PAIN-002

**Pain Point:** Selected results do not travel with enough identity,
completeness, or missing-context visibility.

**Primary Current Work Pattern:** Selecting measurements for sharing.

**Also Appears In:** Reviewing completed results; transferring work between
computers.

**Current Friction:** Users move run data, derived arrays, notebooks, reports,
helper files, and selected-ID notes as ad hoc folders or shared bundles.

**User Impact:** Receivers must reconstruct identity, primary-versus-derived
data, source completeness, and missing context before useful inspection.

**Current Workaround:** Copy folders, attach notes, preserve nearby files, and
explain gaps manually.

**Scopecat Opportunity:** Handoff Packages can export selected Measurement
Records, preserve source identity, make missing context visible, and separate
read-only open from accepted import.

**Related Product Owners:** JNY-001; UC-003, UC-004, UC-006, JNY-001-SMOKE;
CAP-001, CAP-002.

**Boundary / Risk Owner:**
[`handoff.md`](../engineering/prototype-boundaries/handoff.md),
[`handoff-durable-import-storage.md`](../engineering/prototype-boundaries/handoff-durable-import-storage.md),
ADR-0007, ADR-0008, BR-RISK-004, BR-RISK-010.

### BR-PAIN-003

**Pain Point:** Pre-run context and readiness are not reviewable in one place.

**Primary Current Work Pattern:** Checking context before a run.

**Also Appears In:** Reconstructing a reference or rerun; maintaining parameter
and setup files.

**Current Friction:** Users inspect parameter files, setup notes, wiring
spreadsheets, code folders, environment state, services, and notebooks before
starting a run elsewhere.

**User Impact:** Readiness evidence and chosen context remain scattered, so
later run interpretation depends on manual memory.

**Current Workaround:** Follow local check habits, keep notes, inspect files by
hand, and start the run outside Scopecat.

**Scopecat Opportunity:** Prepared-run review can compose declared context,
bounded readiness findings, acknowledgement or deferral, and later Measurement
Record links.

**Related Product Owners:** JNY-002; UC-CAND-002, UC-CAND-003, UC-CAND-006;
CAP-001, CAP-003, CAP-004, CAP-005.

**Boundary / Risk Owner:** [`transition-architecture.md`](transition-architecture.md),
ADR-0004, BR-RISK-001, BR-RISK-008, BR-RISK-009.

### BR-PAIN-004

**Pain Point:** Parameter, setup, registry, and generated context drift without
trusted point-in-time selection.

**Primary Current Work Pattern:** Maintaining parameter and setup files.

**Also Appears In:** Checking context before a run; reconstructing a reference
or rerun.

**Current Friction:** Active JSON, copied seeds, dated variants, generated
line/chip companions, wiring workbooks, registry files, notes, labels, and run
snapshots coexist.

**User Impact:** Users struggle to know which state was trusted, incomplete,
selected, changed, or relevant to a run.

**Current Workaround:** Inspect copies, compare diffs manually, preserve dated
variants, and rely on operator notes.

**Scopecat Opportunity:** Scopecat can preserve point-in-time parameter/setup
context, reviewable diffs, trust/readiness labels, measurement links, and
attention-worthy changes while keeping state families separate.

**Related Product Owners:** JNY-002, JNY-009; UC-CAND-002, UC-CAND-006;
CAP-003, CAP-001 context links.

**Boundary / Risk Owner:** [`transition-architecture.md`](transition-architecture.md),
ADR-0004, BR-RISK-001, BR-RISK-005.

### BR-PAIN-005

**Pain Point:** Code context behind a run is hard to identify later.

**Primary Current Work Pattern:** Reconstructing code context.

**Also Appears In:** Checking context before a run; reconstructing a reference
or rerun; selecting measurements for sharing.

**Current Friction:** Notebooks, helper modules, copied folders, dirty or nested
repositories, generated companions, private imports, and local runtime
assumptions shape runs and analysis.

**User Impact:** Users cannot reliably explain which entrypoint, source root,
helper files, or workspace state mattered for a run or review artifact.

**Current Workaround:** Remember entrypoints, inspect Git opportunistically,
copy folders, and preserve helper files manually.

**Scopecat Opportunity:** Experiment Code Context can record explicit
root/source reference, entrypoint, include policy, stripped notebook source,
declared context links, and later managed-code selection pressure.

**Related Product Owners:** JNY-002, JNY-009; UC-CAND-003; CAP-005.

**Boundary / Risk Owner:**
[`managed-experiment-code-posture.md`](../product/managed-experiment-code-posture.md),
ADR-0005, BR-RISK-009, [`transition-architecture.md`](transition-architecture.md).

### BR-PAIN-006

**Pain Point:** Running and partial measurement lifecycle is ambiguous.

**Primary Current Work Pattern:** Inspecting running measurements.

**Also Appears In:** Reviewing completed results; continuing calibration work.

**Current Friction:** Long-running measurements expose rows, progress, partial
data, stop/interruption state, and temporary fit previews through scripts, live
graphers, files, or notebook output.

**User Impact:** Users cannot tell from durable evidence whether a run is
useful, complete enough, interrupted, recoverable, or invalid.

**Current Workaround:** Inspect live surfaces, notebooks, and partial files
manually, then decide whether to stop, continue, or recover.

**Scopecat Opportunity:** A running monitor can consume explicit lifecycle,
progress, completeness, and partial-data events without taking scan control.

**Related Product Owners:** JNY-004; UC-CAND-004; CAP-006, CAP-001.

**Boundary / Risk Owner:** [`transition-architecture.md`](transition-architecture.md),
ADR-0004, BR-RISK-001.

### BR-PAIN-007

**Pain Point:** Calibration recovery loses fit decisions, proposed writes,
suspicious cases, and continuation intent.

**Primary Current Work Pattern:** Continuing calibration work.

**Also Appears In:** Maintaining parameter and setup files; inspecting running
measurements.

**Current Friction:** Multi-step calibration mixes sequential scans, failed or
suspicious fits, manual review, proposed writes, continuation choices, and
downstream blocking in notebooks and local code.

**User Impact:** Users lose progress, proposed next actions, and cases that
could improve later fit-code review.

**Current Workaround:** Recover from notebook state, rerun helper code,
preserve ad hoc notes, and manually carry continuation choices forward.

**Scopecat Opportunity:** Calibration continuation review can record
user-authored steps, review state, fit outcomes, candidate fit cases,
continuation actions, and handoff to parameter or measurement context.

**Related Product Owners:** JNY-003; UC-CAND-005; CAND-001, CAP-003, CAP-001
context links.

**Boundary / Risk Owner:** [`transition-architecture.md`](transition-architecture.md),
ADR-0004, BR-RISK-001, BR-RISK-005.

### BR-PAIN-008

**Pain Point:** Completed-result review is folder and notebook archaeology.

**Primary Current Work Pattern:** Reviewing completed results.

**Also Appears In:** Selecting measurements for sharing; reconstructing a
reference or rerun.

**Current Friction:** Users reopen stored rows or numeric IDs, browse folders,
inspect notebooks, plot series, review reports, and track selected results
outside a record browser.

**User Impact:** Users struggle to decide what is ready for handoff,
comparison, calibration continuation, or rerun preparation.

**Current Workaround:** Reopen data manually, inspect notebooks and reports,
create plots, and keep readiness notes outside durable record state.

**Scopecat Opportunity:** Post-run review can browse records, distinguish
primary data from derived artifacts, expose missing context, and record
readiness notes before downstream use.

**Related Product Owners:** JNY-008; UC-CAND-007; CAP-001, CAP-002, CAP-005.

**Boundary / Risk Owner:**
[`measurement-records-storage.md`](../engineering/prototype-boundaries/measurement-records-storage.md),
BR-RISK-003, BR-RISK-010.

### BR-PAIN-009

**Pain Point:** Reference and rerun comparison collapses different kinds of
context difference.

**Primary Current Work Pattern:** Reconstructing a reference or rerun.

**Also Appears In:** Checking context before a run; reviewing completed results;
reconstructing code context.

**Current Friction:** Users compare against last-working or notable references
by reopening records, files, code folders, setup notes, parameters, generated
artifacts, and environment evidence.

**User Impact:** Changed, missing, unverified, redacted, unlinked,
same-observed, and not-compared facts collapse into vague gap language.

**Current Workaround:** Reopen old artifacts, compare context manually, and rely
on user/domain judgment for interpretation.

**Scopecat Opportunity:** Selected-reference comparison can report declared
context findings against a user-selected reference while leaving interpretation
to users.

**Related Product Owners:** JNY-009; UC-CAND-006; CAP-001, CAP-003, CAP-005.

**Boundary / Risk Owner:** [`transition-architecture.md`](transition-architecture.md),
ADR-0005, BR-RISK-005, BR-RISK-009.

### BR-PAIN-010

**Pain Point:** Experiment/tool code versions are hard to align across
measurement computers.

**Primary Current Work Pattern:** Moving or synchronizing experiment code
between measurement computers.

**Also Appears In:** Checking context before a run; reconstructing a reference
or rerun; selecting measurements for sharing.

**Current Friction:** Measurement workstations can diverge across notebooks,
helper modules, copied folders, dirty or nested repositories, generated
companions, private imports, local services, and environment assumptions.

**User Impact:** Users cannot confidently tell whether another measurement
computer has the intended experiment/tool code for a run, review, rerun, or
continuation step.

**Current Workaround:** Copy folders, pull Git manually, use shared storage, zip
workspaces, compare files by hand, or ask another operator what is current.

**Scopecat Opportunity:** Experiment Code Context can record or manage selected
code versions behind lab-native actions, compare code context, and later
materialize a selected version onto another machine when that boundary is
earned.

**Related Product Owners:** JNY-002, JNY-009; UC-CAND-003; CAP-005.

**Boundary / Risk Owner:**
[`managed-experiment-code-posture.md`](../product/managed-experiment-code-posture.md),
ADR-0005, BR-RISK-009, [`transition-architecture.md`](transition-architecture.md).

### BR-PAIN-011

**Pain Point:** Primary-data shape is implicit or table-constrained.

**Primary Current Work Pattern:** Recording and reviewing shaped measurement
data.

**Also Appears In:** Recording runs; inspecting running measurements; reviewing
completed results.

**Current Friction:** Current primary rows, CSV-like persisted files, sidecar
arrays, and custom plotting helpers can split measured payload bytes from
intended scan shape, axis roles, expected counts, and completeness.

**User Impact:** Users cannot confidently tell whether a result is a complete
grid, partial grid, trace-per-point measurement, multi-response table, ragged
scan, sidecar-backed result, or derived summary without reading code or
notebooks.

**Current Workaround:** Infer shape from axis columns, unique values, row
counts, metadata sidecars, file names, notebooks, and custom reshape or plotting
helpers.

**Scopecat Opportunity:** Measurement Records can later preserve declared
primary-data shape, axis roles, expected and observed counts, completeness,
sidecar locators, and preview limits separately from source payload bytes.

**Related Product Owners:** JNY-007, JNY-004, JNY-008; UC-CAND-004,
UC-CAND-007; CAP-001, CAP-006.

**Boundary / Risk Owner:**
[`measurement-records-storage.md`](../engineering/prototype-boundaries/measurement-records-storage.md),
ADR-0001, ADR-0002, BR-RISK-003, BR-RISK-005.

## Update Rule

Update this inventory when a new current-state workflow pain changes migration
opportunity, when a pain point is retired by production behavior, or when a row
needs a clearer relation to journey, capability, boundary, risk, or validation
owners.

Do not use this file as a roadmap, validation map, implementation register,
architecture decision record, or active task queue.
