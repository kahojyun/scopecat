# Product Experience Map

## Status And Use

Drafting experience map. Use it to place opportunity pressures across the
fuller lab workflow; do not treat gaps as commitments.

This document describes cross-route experience shape. It is not a product
plan, roadmap, capability map, subsystem spec, API contract, UI spec, storage
design, or prototype scope.

## Purpose

Give future validation work one durable place to describe the fuller product
experience without making any one slice too broad to validate.

```text
complete experience pressure
  -> route or scenario-sized validation slice
  -> fixture, interview, or prototype boundary
  -> later contract or decision only when earned
```

## Composition Rule

Project-level product direction and boundaries are owned by
[`vision.md`](vision.md). Adoption-route definitions live in
[`adoption-routes.md`](adoption-routes.md). Evidence and pain rows live in
[`../evidence/inventory.md`](../evidence/inventory.md). This map only places
current opportunity pressures in the fuller lab workflow so future validation
slices stay narrow while still composing.

## End-To-End Silhouettes

These silhouettes are placement aids. Each line may require several validation
slices; promote only the smallest valuable slice.

| User-facing pressure | Candidate composition | Split point |
| --- | --- | --- |
| Inherited bundle becomes analysis-ready context. | Explain bundle -> package selected runs -> trace derived artifacts. | Packaging known artifacts is separate from generating analysis outputs. |
| One station has multiple computers but one data bottleneck. | Stable record identity -> export/import or shared-storage discovery -> machine-specific locations -> historical records and selected-run previews from another station computer. | Historical browsing may be solved by portable handoff before remote connection; this is a cross-machine access constraint on record browsing and handoff, not a separate LAN browser surface. |
| One cooldown or lab has data spread across multiple stations. | Local durable records -> export/import -> optional shared-storage reference or discovery probe -> cross-station browsing or handoff. | Shared storage is an optional validation question, not required central architecture; indexing, sync, and remote execution remain outside this slice. |
| Experiment code is copied between control computers. | Selected folder and entrypoint -> machine-local config separation -> snapshot/checkpoint -> compare or restore candidate. | One-time folder migration is simpler than ongoing sync; do not promote publish/pull, Git hosting, deployment, automatic sync, or load-selected-version execution from this placement alone. |
| Planned campaign becomes reviewable before scarce experiment time. | Preview intent -> validate bring-up evidence -> review parameter or calibration evidence. | Intent, setup evidence, parameter memory, optional proposal, and write-back remain separate. |
| Long-running measurement remains inspectable while still running. | Explore explicit recording -> expose progress/readiness markers -> optionally save fit or decision evidence -> preserve campaign lineage. | Observation and saved advice do not mutate hardware, scan plans, or claims; append/read semantics still need storage evidence. |
| Informal lab automation becomes explicit. | Freeze grouped calibration intent -> check readiness -> record outcome from lab-owned or future minimal execution -> record quality gates, review decisions, requested next action, and continuation. | Current fixture material tests intent/outcome semantics; run-to-completion is baseline, while resume, retry, review continuation, or selected remeasurement are higher-payoff executor validations. |

## Lab Workflow Reference

Detailed lab workflows live in
[`../evidence/research/extracted/experimental-lab-workflow-reference.md`](../evidence/research/extracted/experimental-lab-workflow-reference.md).
Use that quarantined research note for realistic experiment context. Treat
lab-management details as surrounding context only: they may inform readiness,
lifecycle, minimal context handles, or apply guardrails, but they are not
accepted multi-equipment scheduling, personnel coordination, training,
compliance, ELN, LIMS, or cloud operations scope. Use [`vision.md`](vision.md)
for the project-level non-goals.

## Slicing Rules

Keep validation slices small and user-visible:

- Read existing artifacts before claiming ownership of truth.
- Package known data and context before producing analysis outputs.
- Preview intent and readiness before touching hardware or environments.
- Diagnose gaps before selecting truth, applying changes, or restoring state.
- Preserve declared setup or schema context only when it powers visible output.
- Record advice and proposals as evidence before connecting them to mutation.
- For automation, start with frozen intent, readiness gates, lifecycle, failure
  policy, simulated or lab-owned outcomes, and audit records. A minimal local
  executor is a validation candidate, not assumed scope.

## Opportunity Placement

| Experience area | Current pressure | Placement use |
| --- | --- | --- |
| Existing evidence explanation | Run identity, selected context, code references, missing facts, conflicts, and sharing boundaries. | Anchor post-run artifacts before handoff, comparison, or mutation. |
| Analysis handoff | Selected runs, source identity, portable packages, export/import, and optional shared-storage discovery. | Move enough context to an analysis computer without accepting full publication workflow or central storage. |
| Durable recording and reopen | Ordinary-Python recording, lifecycle evidence, stable opaque IDs, portable manifests, and reopen. | Provide substrate for handoff and read/monitor paths without a managed runner. |
| Code, method, and queue readiness | Copied-code recovery, one-time migration versus ongoing checkpoint/sync pressure, frozen plan or queue intent, dry-run readiness, and grouped-calibration outcomes. | Keep code selection, intent review, readiness, and execution ownership separate. |
| Setup and declared context | Bring-up/setup evidence and manually maintained local schema. | Preserve only context that powers lookup, calculation, visualization, comparison, handoff, or diagnostics. |
| Calibration and running-run observation | Parameter-memory/query pressure and running-run read/monitor support. | Validate observation, fit evidence, and parameter history before proposal/review, real apply, or autonomous calibration. |
| Campaign and generated lineage | Generated protocol, correction, classifier, feedback, and run-family relations. | Preserve scientific lineage without broadening into a full workflow model. |
| Trust and comparison | Known-good diagnostics, scientific comparability, setup reality, and false-confidence gaps. | Compare evidence without accepting rollback, equivalence scoring, or setup truth authority. |
| Derived analysis impact | Figures, reports, fits, claims, exclusions, and calibration or code impact. | Link derived work back to source evidence before considering report generation or publication workflow. |

Same-station data access is a cross-cutting validation constraint, not a
standalone route: stable record identity, legacy source refs, machine-specific
locations, optional shared-storage refs, export/import behavior, and read
capabilities should be checked if a future validation slice needs cross-machine
access. This should not imply remote execution, mandatory NAS, deployed
database scope, or shared instrument-control authority.
