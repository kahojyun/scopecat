# Product Experience Map

## Status And Use

Drafting experience map.

Reader takeaway:

- Accepted direction: compose small evidence, readiness, and handoff journeys.
- Research pressure: realistic lab workflows show where future gaps may exist.
- Action: use this map to place or split `JC` work; do not treat gaps as
  commitments.

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

During measurement:
  -> runs measurement in an existing local stack
  -> records data, metadata, code provenance, calibration context, and run
     lifecycle evidence

After measurement:
  -> later opens an existing run or work bundle
  -> sees source identity, selected context, code references, companion
     artifacts, missing facts, conflicts, and sharing boundaries
  -> selects valuable runs or a run group
  -> creates an immutable pre-analysis handoff snapshot
  -> opens the snapshot offline on the analysis computer

Analysis lineage:
  -> compares current evidence with a known-good reference when trust is weak
  -> links later figures, reports, fits, or claims back to source evidence
```

The silhouette is useful because it shows why small slices need to compose. It
does not mean every step is accepted product direction today.

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
- Treat mutation, authoritative state, managed execution, and automation as
  explicit future-decision boundaries.

## Current And Candidate Journey Coverage

When placing new work, first check whether it fits an existing `JC`; otherwise
create a narrow candidate with evidence and non-goals.

| State | Journey | Covers |
| --- | --- | --- |
| Current | `JC-001` | Post-run explanation of an existing run or work bundle. |
| Current | `JC-002` | Selected-run analysis handoff. |
| If validated | `JC-003` | Calibration review before write-back. |
| If validated | `JC-007` | Pre-run scan or method intent. |
| If validated | `JC-008` | Dry-run package readiness before execution. |
| If validated | `JC-009` | Known-good diagnostic comparison. |
| If validated | `JC-010` | Scientific comparability review. |
| If validated | `JC-011` | Passive measurement-time decision support. |
| Later | Analysis lineage | Figures, reports, fits, and claims. |

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
