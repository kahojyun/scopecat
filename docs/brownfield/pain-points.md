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
- The coverage-check column exists only to confirm that older exploration
  pressure remains represented. It does not define the row structure.
- Pain rows describe user friction and migration opportunity; they do not own
  validation evidence, implementation entrypoints, or active tasks.
- Non-claims are part of the row. Do not turn a pain point into adjacent
  execution, parsing, storage, or hardware authority by implication.

## Pain Points

| ID | Current Work Pattern | Pain Point | Current Workflow Friction | User Impact And Workaround | Scopecat Opportunity | Coverage Check | Related Owners | Non-Claims |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BR-PAIN-001 | Recording runs | Run evidence is scattered across storage, sidecars, notebooks, and folders. | Experiment scripts create Data Vault-style rows and numeric IDs while notebooks, generated companions, parameter snapshots, CSV/NPZ/JSON files, and analysis artifacts accumulate nearby. | Users infer source identity, primary data, transformed data, and context from filenames, folder adjacency, notebook cells, and memory. | Measurement Records can give externally produced runs a local identity, source posture, normalized primary-data state, declared references, and explicit ambiguity. | Measurement boundary; primary-data shape evidence; run-adjacent context. | JNY-007, JNY-008; UC-001, UC-002, UC-CAND-007; CAP-001 | No raw legacy parser, final storage schema, broad plotting model, automatic source repair, or scientific-validity claim. |
| BR-PAIN-002 | Selecting measurements for sharing | Selected results do not travel with enough identity, completeness, or missing-context visibility. | Users move useful run data, derived arrays, notebooks, reports, helper files, and selected-ID notes as ad hoc folders or shared bundles. | Senders and receivers reconstruct identity, primary-versus-derived data, source completeness, and missing context before they can inspect the result. | Handoff Packages can export selected Measurement Records, preserve source identity, make missing context visible, and separate read-only open from accepted import. | Selected handoff; package review; linked context. | JNY-001; UC-003, UC-004, UC-006, JNY-001-SMOKE; CAP-001, CAP-002 | No report generator, automatic analysis DAG traversal, central sync service, authenticity claim, or broad linked-payload import. |
| BR-PAIN-003 | Checking context before a run | Pre-run context and readiness are not reviewable in one place. | Users inspect parameter files, setup notes, wiring spreadsheets, code folders, environment state, services, and notebooks before starting a run elsewhere. | Readiness evidence and chosen context remain scattered; users rely on manual inspection and local habits before run start. | Prepared-run review can compose declared context, bounded readiness findings, acknowledgement or deferral, and later Measurement Record links without granting run-start authority. | Prepared-run context; environment readiness; setup/code/reference inputs. | JNY-002; UC-CAND-002, UC-CAND-003, UC-CAND-006; CAP-001, CAP-003, CAP-004, CAP-005 | No run-start permission, hardware apply, scheduler, environment mutation, recovery authority, or approval bureaucracy. |
| BR-PAIN-004 | Maintaining parameter and setup files | Parameter, setup, registry, and generated context drift without trusted point-in-time selection. | Active JSON, copied seeds, dated variants, generated line/chip companions, wiring workbooks, registry files, notes, labels, and run snapshots coexist. | Users struggle to know which parameter/setup state is trusted, incomplete, selected, changed, or relevant to a run; they inspect copies and diffs manually. | Scopecat can preserve point-in-time parameter/setup context, reviewable diffs, trust/readiness labels, measurement links, and attention-worthy changes while keeping state families separate. | Parameter state; setup binding; station registry pressure; generated companions. | JNY-002, JNY-009; UC-CAND-002, UC-CAND-006; CAP-003, CAP-001 context links | No hardware write-back, universal parameter schema, station registry schema, wiring importer, generator execution, automatic invalidation, or live hardware truth. |
| BR-PAIN-005 | Reconstructing code context | Code and workspace identity behind a run is ambiguous and may be hardware-active. | Notebooks, helper modules, copied folders, dirty or nested repositories, generated companions, private imports, and local runtime assumptions shape runs and analysis. | Users remember entrypoints, inspect Git opportunistically, copy folders, and preserve helper files manually, but still cannot reliably explain which code context mattered. | Experiment Code Context can record explicit root/source reference, entrypoint, include policy, stripped notebook source, declared context links, and later managed-code selection pressure. | Experiment-code context; generated code companions; environment assumptions. | JNY-002, JNY-009; UC-CAND-003; CAP-005 | No code execution, dependency closure, Git authority, record-all behavior, package management, managed runner, workflow/DAG model, or runtime-readiness claim. |
| BR-PAIN-006 | Inspecting running measurements | Running and partial measurement lifecycle is ambiguous. | Long-running measurements expose rows, progress, partial data, stop/interruption state, and temporary fit previews through scripts, live graphers, files, or notebook output. | Users inspect partial state manually and decide whether a run is useful, complete enough, should stop, or should recover without durable lifecycle/completeness evidence. | A running monitor can consume explicit lifecycle, progress, completeness, and partial-data events without taking scan control. | Running inspection; partial data; live range/fit preview pressure. | JNY-004; UC-CAND-004; CAP-006, CAP-001 | No scan-plan changes, automatic retune, autonomous calibration, scheduling, or hardware safety ownership. |
| BR-PAIN-007 | Continuing calibration work | Calibration recovery loses fit decisions, proposed writes, suspicious cases, and continuation intent. | Multi-step calibration mixes sequential scans, failed or suspicious fits, manual review, proposed writes, continuation choices, and downstream blocking in notebooks and local code. | Users recover progress and next actions from notebook state, rerun helper code, keep ad hoc notes, and often lose cases useful for later fit-code improvement. | Calibration continuation review can record user-authored steps, review state, fit outcomes, candidate fit cases, continuation actions, and handoff to parameter or measurement context. | Calibration continuation; fit-case capture; lab-internal validation dataset pressure. | JNY-003; UC-CAND-005; CAND-001, CAP-003, CAP-001 context links | No fitting engine, quality scoring, automatic retry, Scopecat-decided write-back, general scheduler, remote execution, resource arbitration, or public dataset format. |
| BR-PAIN-008 | Reviewing completed results | Completed-result review is folder and notebook archaeology. | After a run, users reopen stored rows or numeric IDs, browse folders, inspect notebooks, plot series, review reports, and track selected results outside a record browser. | Users struggle to decide what is ready for handoff, comparison, calibration continuation, or rerun preparation; static reports can hide source data and transformations. | Post-run review can browse records, distinguish primary data from derived artifacts, expose missing context, and record readiness notes before downstream use. | Completed-result review; post-run browsing and plotting; derived artifacts. | JNY-008; UC-CAND-007; CAP-001, CAP-002, CAP-005 | No report truth, automatic analysis provenance, publication-grade plotting, or user/domain conclusion support. |
| BR-PAIN-009 | Reconstructing a reference or rerun | Reference and rerun comparison collapses different kinds of context difference. | Users compare against last-working or notable references by reopening records, files, code folders, setup notes, parameters, generated artifacts, and environment evidence. | Changed, missing, unverified, redacted, unlinked, same-observed, and not-compared facts collapse into vague gap language; users still provide domain judgment. | Selected-reference comparison can report declared context findings against a user-selected reference while leaving interpretation to users. | Selected reference comparison; rerun preparation; code/setup/context differences. | JNY-009; UC-CAND-006; CAP-001, CAP-003, CAP-005 | No setup truth, user-judgment scoring, rollback, deployment, remote execution, or universal physical setup model. |

## Update Rule

Update this inventory when a new current-state workflow pain changes migration
opportunity, when a pain point is retired by production behavior, or when a
row needs a clearer relation to journey, capability, risk, or validation
owners.

Do not use this file as a roadmap, validation map, implementation register,
architecture decision record, or active task queue.
