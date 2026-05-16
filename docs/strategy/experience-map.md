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
| One station has multiple computers but one data bottleneck. | Stable record identity -> export/import or shared-storage discovery -> machine-specific locations -> historical records and selected-run previews from another station computer. | Historical browsing may be solved by portable handoff before remote connection; this is a cross-machine access constraint on record browsing and handoff, not a separate LAN browser surface. Live observation belongs to later read/monitor or remote-execution validation unless it proves separate adoption payoff. |
| One cooldown or lab has data spread across multiple stations. | Local durable records -> optional NAS/shared-storage publish -> local index cache over manifests -> cross-station browsing or handoff. | Shared storage is an optional transport and discovery backend, not required central architecture; remote execution remains outside this slice. |
| Experiment code is copied between control computers. | Selected folder and entrypoint -> machine-local config separation -> checkpoint/compare -> explicit publish or pull/update. | One-time folder migration is simpler than ongoing sync; do not promote Git hosting, deployment, automatic sync, or load-selected-version execution from this placement alone. |
| Planned campaign becomes reviewable before scarce experiment time. | Preview intent -> validate bring-up evidence -> review parameter or calibration evidence. | Intent, setup evidence, parameter memory, optional proposal, and write-back remain separate. |
| Long-running measurement remains inspectable while still running. | Explore explicit recording -> expose progress/readiness markers -> optionally save fit or decision evidence -> preserve campaign lineage. | Observation and saved advice do not mutate hardware, scan plans, or claims; append/read semantics still need storage evidence. |
| Informal lab automation becomes explicit. | Freeze grouped calibration intent -> check readiness -> record outcome from lab-owned or future minimal execution -> record quality gates, review decisions, requested next action, and continuation. | Current fixture tests intent/outcome semantics; run-to-completion is baseline, while resume, retry, review continuation, or selected remeasurement are the higher-payoff executor validations. |

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
  executor is a validation candidate, not assumed scope. It should be validated
  only when the adoption route creates visible workflow payoff beyond a cleaner
  manifest and justifies rewriting the relevant experiment or calibration code.
  It needs an accepted owner, safety assumptions, stop behavior, safe-disable
  behavior, and audit boundary before it becomes product direction.

## Current And Candidate Journey Coverage

The canonical candidate wording, evidence basis, drafting signal, and main
boundary live in
[`../evidence/inventory.md`](../evidence/inventory.md).
This map only shows where those `JC` rows sit in the larger experience. It does
not own evidence rank, current phase, acceptance status, fixture results, or
prototype boundaries.

If new work needs a new `JC`, update the evidence owner or a narrower `JC`
owner before this placement table becomes the source of truth.

| Experience area | Current or candidate `JC` rows | Placement use |
| --- | --- | --- |
| Existing evidence explanation | `JC-001` | Anchor post-run artifacts, selected context, code references, missing facts, conflicts, and sharing boundaries before handoff, comparison, or mutation. |
| Analysis handoff | `JC-002` | Move selected runs and enough context to an analysis computer as an immutable pre-analysis snapshot, with export/import or optional shared-storage discovery as the first cross-machine answer. |
| Durable recording and reopen | `JC-015` | Explore ordinary-Python recording, lifecycle evidence, running-run reads, stable opaque IDs, portable manifests, and reopen before richer handoff or read/monitor paths depend on recorded inputs. |
| Code, method, and queue readiness | `JC-004`, `JC-007`, `JC-008`, `JC-013` | Separate copied-code provenance, one-time migration from ongoing checkpoint/sync pressure, frozen plan or queue intent, dry-run or mock-queue readiness, simulated or lab-owned grouped-calibration outcomes, and shared asset drift diagnostics. |
| Setup and declared context | `JC-005`, `JC-012` | Preserve bring-up/setup evidence and only maintain declared local schema when it powers visible lookup, calculation, visualization, comparison, handoff, or diagnostics. |
| Calibration and running-run observation | `JC-003`, `JC-011` | Place parameter-memory/query pressure and running-run read/monitor support before optional saved advice, optional proposal/review, real apply, or autonomous calibration. |
| Bounded local execution hypothesis | `JC-016` | Place the possible bridge from reviewed intent, local execution evidence, parameter memory, code-version selection, and advisory evidence into one bounded local-run decision without treating runtime ownership as accepted here. |
| Campaign and generated lineage | `JC-006` | Preserve generated protocol, correction, classifier, feedback, and run-family relations without broadening into a full scientific workflow model. |
| Trust and comparison | `JC-009`, `JC-010` | Place known-good diagnostics and scientific comparability review without accepting rollback, equivalence scoring, or setup truth authority. |
| Derived analysis impact | `JC-014` | Link figures, reports, fits, and claims back to source evidence before considering report generation or publication workflow. |

Same-station data access is now a cross-cutting validation constraint, not a
candidate `JC`: stable record identity, legacy source refs, machine-specific
locations, optional shared-storage refs, export/import behavior, and read
capabilities should be checked if `JC-001`, `JC-002`, or `JC-015` need
cross-machine access. This should not imply remote execution, mandatory NAS,
deployed database scope, or shared instrument-control authority. If multiple
station computers can reach the same instruments, conflict coordination remains
external unless a later resource/runtime journey accepts leases, permissions,
arbitration, failure behavior, and safety assumptions.

Adjacent steps are context, not prototype scope. The tracker owns current
phase and coordination status; owning `JC` documents own validation
boundaries.
