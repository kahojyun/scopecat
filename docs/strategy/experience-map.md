# Product Experience Map

## Status And Use

Drafting experience map. Use it to place or split `JC` work across the fuller
lab workflow; do not treat candidate gaps as commitments.

This document describes cross-journey experience shape. It is not a product
plan, roadmap, capability map, subsystem spec, API contract, UI spec, storage
design, or prototype scope.

## Purpose

Give future journey work one durable place to describe the fuller product
experience without making any one `JC-###` too broad to validate.

The canonical `JC` wording, evidence basis, drafting signal, and main boundary
live in
[`../evidence/inventory.md`](../evidence/inventory.md).
This map only shows how current and candidate journeys compose.

```text
complete experience pressure
  -> journey-sized validation slice
  -> fixture/prototype boundary
  -> later contract or decision only when earned
```

## Composition Rule

Project-level product direction and boundaries are owned by
[`vision.md`](vision.md). Adoption-route definitions live in
[`adoption-routes.md`](adoption-routes.md). This map only places current and
candidate `JC` rows in the fuller lab workflow so future slices stay narrow
while still composing.

## End-To-End Journey Silhouettes

These silhouettes are placement aids. Each line may cross several `JC`
boundaries; promote only the smallest valuable slice.

| User-facing pressure | Candidate composition | Split point |
| --- | --- | --- |
| Inherited bundle becomes analysis-ready context. | Explain bundle -> package selected runs -> trace derived artifacts. | Packaging known artifacts is separate from generating analysis outputs. |
| Planned campaign becomes reviewable before scarce experiment time. | Preview intent -> validate bring-up evidence -> review calibration proposal. | Intent, setup evidence, proposal, and write-back remain separate. |
| Long-running measurement produces decision-grade evidence. | Record durable run -> replay decision support -> preserve campaign lineage. | Advice records evidence; it does not mutate hardware, scan plans, or claims. |
| Informal lab automation becomes explicit. | Freeze queue intent -> mock readiness -> review proposal -> hand one reviewed package to one lab-owned runtime for one bounded local run. | Early automation can validate contracts; the bounded local run needs an accepted runtime boundary. |

## Lab Workflow Reference

Detailed lab workflows live in
[`../evidence/research/extracted/experimental-lab-workflow-reference.md`](../evidence/research/extracted/experimental-lab-workflow-reference.md).
Use that quarantined research note for realistic experiment context. Treat
lab-management details as surrounding context only: they may inform readiness,
lifecycle, minimal context handles, or apply guardrails, but they are not
accepted multi-equipment scheduling, personnel coordination, training,
compliance, ELN, LIMS, or cloud operations scope. Use [`vision.md`](vision.md)
for the project-level non-goals.

## Journey Slicing Rules

Keep journey slices small and user-visible:

- Read existing artifacts before claiming ownership of truth.
- Package known data and context before producing analysis outputs.
- Preview intent and readiness before touching hardware or environments.
- Diagnose gaps before selecting truth, applying changes, or restoring state.
- Preserve declared setup or schema context only when it powers visible output.
- Record advice and proposals as evidence before connecting them to mutation.
- For automation, start with frozen intent, readiness gates, lifecycle, failure
  policy, replay or shadow behavior, and audit records. A bounded local run
  needs an accepted runtime owner, safety assumptions, stop behavior, and audit
  boundary.

## Current And Candidate Journey Coverage

The canonical candidate wording, evidence basis, drafting signal, and main
boundary live in
[`../evidence/inventory.md`](../evidence/inventory.md).
This map only shows where those `JC` rows sit in the larger experience.

If new work needs a new `JC`, update the evidence owner or a narrower `JC`
owner before this placement table becomes the source of truth.

| Experience area | Current or candidate `JC` rows | Placement use |
| --- | --- | --- |
| Existing evidence explanation | `JC-001` | Anchor post-run artifacts, selected context, code references, missing facts, conflicts, and sharing boundaries before handoff, comparison, or mutation. |
| Durable recording and reopen | `JC-015` | Let ordinary Python create stable run identity, append data, expose lifecycle state, support checkpoint-safe reads, and reopen by stable ID before richer handoff or advisory paths depend on recorded inputs. |
| Analysis handoff | `JC-002` | Move selected runs and enough context to an analysis computer as an immutable pre-analysis snapshot. |
| Code, method, and queue readiness | `JC-004`, `JC-007`, `JC-008`, `JC-013` | Separate copied-code provenance, frozen plan or queue intent, dry-run or mock-queue readiness, and shared asset drift diagnostics. |
| Setup and declared context | `JC-005`, `JC-012` | Preserve bring-up/setup evidence and only maintain declared local schema when it powers visible lookup, calculation, visualization, comparison, handoff, or diagnostics. |
| Calibration and advisory automation | `JC-003`, `JC-011` | Validate proposal, impact, replay, advisory, and shadow-loop evidence before real apply or autonomous calibration. |
| Bounded local runtime handoff | `JC-016` | One reviewed package handed to one lab-owned runtime for one bounded local run, with runtime owner, stop behavior, failure policy, and audit record explicit. |
| Campaign and generated lineage | `JC-006` | Preserve generated protocol, correction, classifier, feedback, and run-family relations without broadening into a full scientific workflow model. |
| Trust and comparison | `JC-009`, `JC-010` | Place known-good diagnostics and scientific comparability review without accepting rollback, equivalence scoring, or setup truth authority. |
| Derived analysis impact | `JC-014` | Link figures, reports, fits, and claims back to source evidence before considering report generation or publication workflow. |

Adjacent steps are context, not prototype scope. The tracker owns current
phase and coordination status; owning `JC` documents own validation
boundaries.
