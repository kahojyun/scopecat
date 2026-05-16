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
| Planned campaign becomes reviewable before scarce experiment time. | Preview intent -> validate bring-up evidence -> review parameter or calibration evidence. | Intent, setup evidence, parameter memory, optional proposal, and write-back remain separate. |
| Long-running measurement remains inspectable while still running. | Explore explicit recording -> expose progress/readiness markers -> optionally save fit or decision evidence -> preserve campaign lineage. | Observation and saved advice do not mutate hardware, scan plans, or claims; append/read semantics still need storage evidence. |
| Informal lab automation becomes explicit. | Freeze grouped calibration intent -> check readiness -> record outcome from lab-owned or future minimal execution -> record quality gates, review decisions, and requested next action. | Current fixture validates intent/outcome semantics; any Scopecat-owned execution needs observed runtime evidence and an accepted boundary. |

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
  policy, simulated or lab-owned outcomes, and audit records. A minimal local
  executor is a validation candidate, not assumed scope; it needs an accepted
  owner, safety assumptions, stop behavior, safe-disable behavior, and audit
  boundary before it becomes product direction.

## Current And Candidate Journey Coverage

The canonical candidate wording, evidence basis, drafting signal, and main
boundary live in
[`../evidence/inventory.md`](../evidence/inventory.md).
This map only shows where those `JC` rows sit in the larger experience. It
keeps a compact status posture so unaccepted hypotheses do not look equivalent
to accepted or draft journey work; detailed evidence rank and prototype
boundaries still live in the owning evidence or journey docs.

If new work needs a new `JC`, update the evidence owner or a narrower `JC`
owner before this placement table becomes the source of truth.

| Experience area | Current or candidate `JC` rows | Status posture | Placement use |
| --- | --- | --- | --- |
| Existing evidence explanation | `JC-001` | Accepted boundary | Anchor post-run artifacts, selected context, code references, missing facts, conflicts, and sharing boundaries before handoff, comparison, or mutation. |
| Analysis handoff | `JC-002` | Draft boundary | Move selected runs and enough context to an analysis computer as an immutable pre-analysis snapshot. |
| Durable recording and reopen | `JC-015` | Substrate hypothesis | Explore ordinary-Python recording, lifecycle evidence, running-run reads, and reopen by stable ID before richer handoff or read/monitor paths depend on recorded inputs. Append/read atomicity and buffering are not settled here. |
| Code, method, and queue readiness | `JC-004`, `JC-007`, `JC-008`, `JC-013` | Candidate or fixture-gated | Separate copied-code provenance, frozen plan or queue intent, dry-run or mock-queue readiness, simulated or lab-owned grouped-calibration outcomes, and shared asset drift diagnostics. |
| Setup and declared context | `JC-005`, `JC-012` | Candidate or ADR-gated | Preserve bring-up/setup evidence and only maintain declared local schema when it powers visible lookup, calculation, visualization, comparison, handoff, or diagnostics. |
| Calibration and running-run observation | `JC-003`, `JC-011` | Candidate or fixture-gated | Place parameter-memory/query pressure and running-run read/monitor support before optional saved advice, optional proposal/review, real apply, or autonomous calibration. |
| Bounded local execution hypothesis | `JC-016` | Capability hypothesis only | Place the possible bridge from reviewed intent, local execution evidence, parameter memory, code-version selection, and advisory evidence into one bounded local-run decision; do not treat runtime ownership as accepted. |
| Campaign and generated lineage | `JC-006` | Candidate | Preserve generated protocol, correction, classifier, feedback, and run-family relations without broadening into a full scientific workflow model. |
| Trust and comparison | `JC-009`, `JC-010` | Candidate | Place known-good diagnostics and scientific comparability review without accepting rollback, equivalence scoring, or setup truth authority. |
| Derived analysis impact | `JC-014` | Candidate | Link figures, reports, fits, and claims back to source evidence before considering report generation or publication workflow. |

Adjacent steps are context, not prototype scope. The tracker owns current
phase and coordination status; owning `JC` documents own validation
boundaries.
