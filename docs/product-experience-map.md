# Product Experience Map

## Status And Use

Drafting experience map.

Reader takeaway:

- Accepted direction: compose small evidence, readiness, and handoff journeys.
- Research pressure: realistic lab workflows show where future gaps may exist.
- Action: use this map to place or split `JC` work; do not treat gaps as
  commitments.
- Boundary rule: keep explanation, packaging, comparison, proposal, advisory,
  mutation, and generated-output work in separate validation slices unless a
  narrower owner explicitly joins them.

This document describes cross-journey experience shape. It is not a product
plan, roadmap, capability map, subsystem spec, API contract, UI spec, storage
design, or prototype scope.

## Purpose

Give future journey work one durable place to describe the fuller product
experience without making any one `JC-###` too broad to validate.

A `JC` is a journey candidate: a narrow, evidence-backed slice of product
behavior with its own validation boundary.

If a future journey touches one of these steps, create or update the owning
`JC` with a validation boundary, evidence source, and explicit non-goals.

Earlier documents intentionally kept `JC-001` and `JC-002` narrow enough for
fixture-scale validation. That left some complete-experience pressure scattered
across tracker rows, top-level pain narratives, future-pressure notes, and
journey non-goals.

```text
complete experience pressure
  -> journey-sized validation slice
  -> fixture/prototype boundary
  -> later contract or decision only when earned
```

## How Candidate Journeys Compose

Project-level product direction and boundaries are owned by
[`vision.md`](vision.md). This map only shows how validated and candidate
journeys may compose into a fuller user experience.

One representative long-form experience is:

```text
Before measurement:
  experiment user prepares work
  -> previews intended scan or method shape
  -> stages measurement code, config, and environment context for a target
     measurement computer
  -> validates local readiness without taking over hardware control
  -> brings up sample, setup, and calibration evidence as context, not as
     Scopecat-owned physical truth

During measurement:
  -> runs measurement in an existing local stack
  -> records data, metadata, code provenance, calibration context, and run
     lifecycle evidence
  -> gets passive, replayable decision evidence from explicitly recorded slices
     when a long-running run needs continue, stop, repeat, retune, or zoom
     judgment

After measurement:
  -> later opens an existing run or work bundle
  -> sees source identity, selected context, code references, companion
     artifacts, missing facts, conflicts, and sharing boundaries
  -> selects valuable runs or a run group
  -> creates an immutable pre-analysis handoff snapshot
  -> opens the snapshot offline on the analysis computer

Analysis lineage:
  -> compares current evidence with a known-good reference when trust is weak
  -> reviews whether valid-looking runs, setup states, or method variants are
     scientifically comparable
  -> links later figures, reports, fits, or claims back to source evidence
```

The silhouette is useful because it shows why small slices need to compose. It
does not mean every step is accepted product direction today.

## End-To-End Journey Silhouettes

These silhouettes are placement aids. Each line may cross several `JC`
boundaries; promote only the smallest valuable slice.

| E2E pressure | Candidate composition | Split point |
| --- | --- | --- |
| Inherited bundle becomes analysis-ready context. | `JC-001` explains the bundle -> `JC-002` packages selected runs -> `JC-014` later links derived figures, fits, reports, or claims back to the snapshot and source runs. | `JC-002` packages already-known artifacts; it does not generate or own derived analysis outputs. |
| Existing method moves toward another control computer. | `JC-004` cleans notebook/copied-code provenance -> `JC-013` compares copied method or config assets with a known-good source -> `JC-008` validates a dry-run package. | Code/config diagnostics and readiness records are not deployment, package installation, environment sync, or remote execution. |
| Planned campaign becomes reviewable before scarce experiment time. | `JC-007` previews and freezes intent -> `JC-005` validates bring-up evidence -> `JC-003` reviews calibration proposals before mutation. | Intent preview, setup evidence, calibration proposal, and write-back are separate boundaries. |
| Long-running measurement produces decision-grade evidence. | Explicit recording feeds `JC-011` passive decision support -> `JC-006` preserves generated protocol, correction, and run-family lineage -> `JC-003` or `JC-014` can later review calibration or analysis impact. | Measurement-time advice records evidence; it does not mutate scan plans, hardware, calibration, or analysis claims. |
| Informal lab automation becomes explicit. | Existing notebook-cell queues or script loops -> `JC-007` freezes plan intent -> `JC-008` mock-validates queue readiness and failure policy -> `JC-003` or `JC-011` validates calibration proposal or advisory behavior before real apply. | Early automation journeys may validate queue, lifecycle, readiness, and proposal contracts with mock or recorded inputs; real hardware apply and unattended execution need narrower accepted runtime boundaries. |
| Valid-looking results need trust and comparison. | `JC-009` compares current evidence with a known-good reference -> `JC-010` reviews scientific comparability -> `JC-012` uses declared local schema only when it powers a concrete comparison, lookup, visualization, handoff, or diagnostic output. | Diagnostic comparison is not rollback; comparability review is not equivalence scoring; declared setup context is not software-proven truth. |
| Minimal local schema earns maintenance effort. | `JC-012` starts with one setup, sample, or campaign schema that produces useful output -> later journeys may reuse the same declared context in handoff, diagnostics, comparability, or lineage. | Manual metadata is justified by immediate value, not by future ontology completeness. |

## Lab Workflow Reference

Detailed lab workflows live in
[`research/extracted/experimental-lab-workflow-reference.md`](research/extracted/experimental-lab-workflow-reference.md).
Use that quarantined research note for realistic experiment context such as
cross-computer code staging, sample bring-up, calibration chains, measurement
campaign decisions, analysis handoff, report lineage, and lab-management
surroundings.

Here, "product-relevant pressure" means workflow evidence that may justify
future journey work, but is not accepted scope. Only that pressure belongs here:

- code, config, dependency, and setup context may need to move to a target
  measurement computer before a run;
- data, source evidence, and selected context may need to move from a
  measurement computer to an analysis computer after a run;
- calibration, setup, generated-protocol, correction, and lifecycle evidence
  can affect whether a run is understandable, comparable, or safe to hand off;
- these details should shape journey slicing without accepting hardware
  control, scheduling, deployment, write-back, ELN/LIMS, report-generation, or
  full lab-management scope.

## Composition Rules

Prefer small validated slices before mutation:

- Read existing artifacts before claiming ownership of truth.
- Package known data and context before producing new analysis outputs.
- Preview intent and readiness before touching hardware or environments.
- Diagnose gaps before selecting truth, applying changes, or restoring state.
- Preserve declared setup or schema context only when it produces a visible
  user output.
- Record measurement-time advice as evidence before connecting it to
  calibration, scan-plan, or hardware mutation.
- Link derived analysis artifacts back to source evidence before generating
  reports or scoring claim correctness.
- Treat mutation, authoritative state, managed execution, and automation as
  explicit future-decision boundaries.

## JC Boundary Placement

Use these boundaries when a future journey looks too large:

| Boundary | Put inside the `JC` | Keep outside until separately validated |
| --- | --- | --- |
| Explanation | Roles, relations, conflicts, missing facts, provenance, and sharing boundary for existing artifacts. | Repair, import, execution, source-of-record authority, or scientific equivalence. |
| Handoff packaging | Immutable package of already-known selected data, required sidecars, context slots, and warnings. | Generated plots, fits, reports, publication arrays, managed analysis execution, or public publish workflow. |
| Readiness | Static or explicitly supplied checks that expose missing dependencies, unsafe assumptions, or portability gaps. | Installation, environment mutation, deployment, queueing, remote execution, or driver repair. |
| Comparison | Differences, confidence gaps, known-good references, and unresolved ambiguity. | Rollback, restore, automatic normalization, authoritative winner selection, or claim correctness. |
| Proposal | Reviewable calibration, setup, or parameter change with source evidence and impact. | Hidden write-back, autonomous calibration, apply semantics, or rollback guarantees. |
| Advisory | Replayable stop, continue, repeat, retune, zoom, or quality evidence from recorded data. | Hardware control, scan-plan mutation, parameter write-back, passive scraping, or opaque AI advice. |
| Declared context | One local setup, sample, topology, alias, or schema used for a visible job. | Universal ontology, exhaustive inventory, or software-proof of physical truth. |

## Automation Placement Near JC Decisions

Existing labs may already automate through notebooks, scripts, queued cells,
framework schedulers, and local calibration loops. Treat those as current-state
automation evidence, not as proof that Scopecat owns the hardware runtime.

Automation-oriented `JC` work can start before real hardware apply when the
slice validates one of these contracts:

- frozen plan or queue intent;
- readiness gates and preflight evidence;
- explicit lifecycle and failure policy;
- mock, recorded-input, or shadow replay behavior;
- reviewed calibration, parameter, or next-step proposals;
- audit records for what was requested, checked, approved, run, skipped,
  stopped, or failed.

Do not hide automation inside a passive journey. If a journey introduces
unattended execution, real instrument apply, resource locking, rollback, or
autonomous calibration, the owning `JC` or decision must state the instrument
runtime owner, safety assumptions, stop behavior, and audit record.

## Current And Candidate Journey Coverage

When placing new work, first check whether it fits an existing `JC`; otherwise
create a narrow candidate with evidence and non-goals.

| State | Journey | Covers | Boundary reminder |
| --- | --- | --- | --- |
| Current | `JC-001` | Post-run explanation of an existing run or work bundle. | Read-only passive evidence view; no execution, mutation, import, repair, or truth ownership. |
| Current | `JC-002` | Selected-run analysis handoff. | Immutable pre-analysis snapshot; no generated analysis outputs or final reader/API/UI contract. |
| If validated | `JC-003` | Calibration proposal, review, and impact before write-back. | May validate proposal and shadow-loop evidence for later automation; real apply, rollback, and autonomous calibration need accepted runtime boundaries. |
| If validated | `JC-004` | Notebook, copied-code, package, and generated-bytecode provenance cleanup. | Evidence links only; no automatic notebook-state capture, package registry, or managed runner. |
| If validated | `JC-005` | Sample/device bring-up and setup readiness evidence. | Declared or observed evidence only; no device communication, setup apply, or physical-truth authority. |
| If validated | `JC-006` | Generated protocol, correction, classifier, feedback, and run-family lineage. | Preserve relations; do not broaden into a full scientific workflow model. |
| If validated | `JC-007` | Pre-run scan, method, or queue intent preview. | Preview, diff, or freeze intent only; later queue execution still needs lifecycle, runtime, and stop-behavior boundaries. |
| If validated | `JC-008` | Dry-run or mock-queue package readiness before execution. | Can validate queue package, preflight, and failure-policy contracts; no real worker fleet, remote execution, or device control. |
| If validated | `JC-009` | Known-good diagnostic comparison. | Comparison and diagnostic package only; no rollback, restore, installation, driver mutation, or control-PC repair. |
| If validated | `JC-010` | Scientific comparability review. | Evidence and gap review only; no equivalence scoring, generic normalization, or universal setup model. |
| If validated | `JC-011` | Measurement-time decision support from recorded inputs. | May validate advisory or shadow automation behavior; real hardware control, scan mutation, write-back, or scraping adapter matrices remain separate boundaries. |
| If validated | `JC-012` | Small declared setup or local schema to useful context output. | Manual schema must power lookup, calculation, visualization, comparison, handoff, or diagnostics; no ontology-first inventory. |
| If validated | `JC-013` | Shared code or configuration asset drift diagnostics. | Known-good and reusable-layer evidence only; no Git hosting, package registry, deployment, or automatic environment sync. |
| If validated | `JC-014` | Figure, report, fit, or claim impact lineage. | Trace impact back to source evidence; no full ELN, report generator, publication workflow, or correctness scoring. |

Adjacent steps are context, not prototype scope. The tracker owns current
phase, priority, and coordination status; owning `JC` documents own validation
boundaries.

## Research-Pressure Gaps, Not Backlog

These pressures help place future `JC` work in the larger experience. They are
not priorities, requirements, commitments, or prototype scope.

Before run:

- Pressure: code, config, dependency, and setup context may need staging onto a
  target measurement computer. Boundary: not deployment or remote execution.
- Pressure: sample/device bring-up and calibration evidence can affect trust.
  Boundary: proposal-versus-apply remains explicit.
- Pressure: declared setup, sample, topology, or schema context may power
  lookup, calculation, visualization, comparison, handoff, or diagnostics.
  Boundary: not a universal setup database.

During run:

- Pressure: live inspection or live preview may be useful before and during a
  run. Boundary: preview and inspection are not managed execution.
- Pressure: completed sweep slices may need fit, quality, anomaly, and
  intent-specific feedback. Boundary: use explicitly recorded data without
  taking over hardware control.
- Pressure: partial, paused, retuned, repeated, corrected, and invalidated run
  evidence may matter. Boundary: record why the operator continued, stopped, or
  returned to calibration without automating the decision.

After run:

- Pressure: figures, reports, fits, and claims need links back to source runs,
  code, context, corrections, exclusions, and unresolved ambiguity. Boundary:
  lineage first, report generation later if ever validated.
- Pressure: failure, interruption, manual intervention, and recovery evidence
  can explain partial or rescued work. Boundary: explanation before managed
  recovery.
