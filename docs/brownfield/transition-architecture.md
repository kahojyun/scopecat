# Brownfield Transition Architecture

## Status

Current brownfield ownership-posture map.

## Purpose

Describe how Scopecat moves authority from current lab workflows to target
Scopecat boundaries one narrow slice at a time.

Use this document for current pattern, transition posture, Scopecat-owned
boundary, and deferred authority. Use
[`../product/target-journeys.md`](../product/target-journeys.md) for canonical
journey/use-case ownership and
[`migration-roadmap.md`](migration-roadmap.md) for sequencing.

## Ownership Posture Vocabulary

Ownership posture records what authority has moved from a brownfield system to
Scopecat. It is separate from delivery maturity.

| Posture | Meaning |
| --- | --- |
| Observe | Scopecat reads or observes legacy/system output without changing it. |
| Record | Scopecat records declared facts, references, receipts, snapshots, or lifecycle evidence from legacy/system behavior. |
| Review | Scopecat provides local review, preview, comparison, or gate behavior while a user or legacy system remains the authority. |
| Bridge | Scopecat adapts explicitly between a legacy/system artifact and a Scopecat-owned boundary. |
| Shadow | Scopecat computes, checks, or validates beside the legacy path, while the legacy path remains authoritative. |
| Assist | Scopecat helps prepare or perform user-directed work without owning final mutation or execution authority. |
| Partial owner | Scopecat owns a narrow durable state, package, receipt, review, or mutation boundary. |
| Primary owner | Scopecat is the primary authority for the named boundary. |
| Retired legacy path | The old path has been explicitly replaced or stopped for the named boundary. |

## Transition Map

| Boundary | Current Pattern | Transition Posture | Scopecat-Owned Boundary | Deferred Authority |
| --- | --- | --- | --- | --- |
| JNY-001 Share A Selected Measurement | Users manually copy selected run data, sidecars, notebooks, reports, or folders, and receivers infer identity and completeness from layout. | `Review`, `Bridge`, and `Partial owner`. | Scopecat-authored handoff package, read-only package open, receiving gate, import plan, selected-record export projection, and approved new-record durable import. | Legacy execution, raw historical file semantics, adapter discovery, sender trust, authenticity, scientific validity, GUI-owned persisted receiving state, archive-backed durable import, linked-context durable import, and existing-record merge/update. |
| JNY-002 Prepare A Manual Run | Users inspect parameter files, code folders, environment state, setup notes, and notebooks manually before a run. | Candidate `Record` and `Review`. | Future prepared-run context review receipt that records selected context, acknowledgement, deferral, or note. | Hardware apply, live write-back, current instrument truth, automatic run start, scheduling, and shared run-context authority. |
| JNY-003 Recover Or Continue Calibration Work | Users recover failed fits, retry decisions, and downstream blocking from scattered notebook state. | Candidate `Record` and `Review`. | Reviewable fit, evidence, action, and continuation summaries; accepted-write pressure for future parameter-state review. | Local sequential execution, Scopecat-decided retry, mutation, write-back, and hardware control. |
| JNY-004 Monitor A Running Measurement | Users inspect long-running measurements through existing scripts, partial files, or live plotting tools. | Candidate `Observe`, `Record`, and `Review`. | Future lifecycle/progress event observation, partial-data markers, and latest-useful-sweep review. | Experiment execution, scan-plan changes, automatic retune, scheduling, and scan control. |
| JNY-007 Record Runs | Users preserve legacy, external, notebook, or manually reviewed measurement facts through copied files, notes, or folder conventions. | `Record`, `Bridge`, and `Partial owner`. | Measurement Record shell, source receipt, reviewed normalized primary-data durable import, record-local declared references, canonical open-by-id record view. | Raw legacy parsing, legacy execution, adapter discovery, reference repair, current instrument truth, opening/browsing/plotting/readiness review, and scientific validity. |
| JNY-008 Browse And Review Completed Results | Users reopen completed results through folders, notebooks, plots, reports, sidecars, and memory. | Candidate `Review` and `Record`. | Future records browser, open/filter/plot surfaces, operator review notes, readiness review, and derived read model as a review convenience. | Final public storage schema, manifest replacement, broad merge import, scientific validity, GUI-owned review state, and canonical source replacement. |
| JNY-009 Reproduce Or Rerun From A Reference | Users compare against references by reopening files, notebooks, setup notes, copied folders, and memory. | Candidate `Record`, `Review`, and possible `Assist`. | Future reference selection, declared context comparison, selected code-context evidence, workspace preparation, and objective finding classification. | Setup truth, user/domain judgment, rollback, dependency closure, code execution, managed deployment, remote execution, and hardware or environment mutation. |
| Experiment Code Context supporting workflow | Code context is reconstructed from copied folders, notebooks, helper libraries, backups, and editable working trees. | Candidate `Record`, `Review`, or `Assist`, depending on consuming use case. | Supporting evidence for code-context recording, comparison, materialization, editable-folder observation, rerun preparation, or GUI review. | Git replacement, package-manager ownership, runtime execution, dependency closure, managed deployment, and universal code-truth claims. |
| Selected Reference Comparison supporting workflow | Users compare current work to last-working or notable references through memory and reopened artifacts. | Candidate `Review`. | Supporting objective comparison findings for declared facts and selected context. | Setup truth, scientific judgment, automatic action, rollback, and universal reference semantics. |
| Setup Binding Snapshot supporting workflow | Setup context is inferred from notes, configuration files, registry files, and operator memory. | Candidate `Record` and `Review`. | Supporting prepared-run or reference-rerun context snapshot when a consuming use case earns it. | Universal setup ontology, live setup truth, hardware topology authority, and automatic compatibility decisions. |

## Update Rule

Update this architecture when a branch changes a brownfield current pattern,
transition posture, Scopecat-owned boundary, or deferred authority.

Do not use this file to track journey goals, canonical use-case membership,
capability maturity, validation evidence, implementation entrypoints, tests,
fixtures, or task sequencing.
