# Document Index

## Purpose

Compact index of high-value docs for readers and future AI sessions. This file
is allowed to change as the documentation set changes; stable documentation
policy belongs in `README.md`.

If this index and a document's own status disagree, trust the document's own
status. Index descriptors are navigation labels, not validation statuses.

## Index

| Document | Descriptor | Use For | Caveat |
| --- | --- | --- | --- |
| `README.md` | Stable policy | Documentation purpose, entry points, and editing rules. | Should stay compact and avoid current file inventory. |
| `AGENTS.md` | Stable policy | Always-applied AI instructions for work inside `docs/`. | Keep operational; do not move long background here. |
| `vision.md` | Drafting project vision | Current project-level direction and boundaries: progressive adoption, explicit recording, complementing existing experiment systems, and clear non-goals. | Not a roadmap, PRD, capability map, API/schema/UI/storage contract, or architecture decision. |
| `jc-analysis-operating-standard.md` | Doc ready operating standard | Repeatable `JC-###` status language, source-map gates, promotion flow, acceptance gates, conflict handling, and reopening rules. | Process owner only; use evidence owner docs for `EV-###`, `PN-###`, `TP-###`, and `JC-###` source material. |
| `product-experience-map.md` | Drafting experience map | Complete-experience shape across journey candidates, boundary modes, and journey coverage gaps. | Not a `JC` owner, accepted product plan, roadmap, capability map, API/schema/UI/storage contract, or prototype scope. |
| `progressive-adoption-progress-tracker.md` | Active tracker | Tracking journey-first discovery, adoption ladders, migration wedges, contracts, decision promotion, and compact cross-journey coordination. | Keep compact; it is not a journey-local task queue. Move detailed ladders, wedges, baselines, contracts, and scheduling or ranking coordination to narrower owner docs once they have multiple active consumers. |
| `evidence-and-pain-point-inventory.md` | W1 evidence owner | W1 owner for evidence, lab/user context, top-level pain narratives, pain/pressure rows, adoption blockers, external-framework baselines, statement-kind separation, anti-patterns, and saturation assessment. | `JC-001` has been promoted out of this inventory; future `JC` process guidance belongs in `jc-analysis-operating-standard.md`. |
| `jc-001/README.md` | First-wedge record | Entry point, audience read paths, accepted boundary, fixture-validated prototype, manifest/public-output contract, and first-wedge history for `JC-001`. | Earned exemplar, not a process owner or folder template for future journey candidates. |
| `jc-002/README.md` | Drafting journey record | Entry point for the selected-run analysis handoff document set, including journey selection, snapshot definition, current/future journey seed, and fixture-backed draft prototype scope. | Drafting only; not an accepted decision, manifest schema, API contract, export format, storage design, or UI spec. |
| `research/README.md` | Stable policy | Research directory purpose and promotion rule. | Does not define product direction. |
| `research/AGENTS.md` | Stable policy | Always-applied AI instructions for work inside `docs/research/`. | Keeps raw research from being treated as product truth. |
| `research/research-index.md` | Working index | Current research inputs, extraction state, caveats, and retention rules. | Research entries are evidence inputs unless separately promoted. |
| `research/extracted/research-acceptance-readiness-triage.md` | Transitional research input | Preferred entry point for deciding which raw research claims are accepted guardrails, evidence, inferences, hypotheses, future pressure, ADR-gated items, or rejected first-slice directions. | Retention and extraction state are owned by `research/research-index.md`. |
| `research/extracted/legacy-experiment-code-sample-validation.md` | Transitional research input | Validation of the raw research triage against two copied legacy experiment code trees; use for concrete evidence on companion artifacts, settings drift, analysis handoff, hardware bring-up, dependency pain, notebook hygiene, and portability pressure. | Retention and extraction state are owned by `research/research-index.md`. |
| `research/greenfield-experimental-automation-architecture-notes.md` | Quarantined research input | Automation architecture pressure, historical vocabulary, candidate boundaries, and questions. | Retention and extraction state are owned by `research/research-index.md`. |
| `research/raw/fricon-legacy-docs/README.md` | Extracting research input | Predecessor project documentation snapshot, especially measurement-history analysis and long-term experiment-memory goals. | Retention and extraction state are owned by `research/research-index.md`; use extracted notes first. |

## Possible Future Areas

This is a reference taxonomy, not a scaffold to create in advance. Add these
areas only when there is durable content with a clear owner and purpose.

```text
docs/
  user/          # Public, redacted MkDocs-facing documentation.
  project/       # Vision, glossary, roadmap, and project context.
  product/       # Personas, evidence, pain points, opportunity maps.
  journeys/      # End-to-end user journeys that cross capabilities.
  architecture/  # System map, ownership, dependencies, contracts.
  capabilities/  # Capability-level adoption, domain, and architecture notes.
  concepts/      # Stable cross-capability domain concept cards.
  decisions/     # Project-wide ADRs.
  research/      # Raw or semi-processed research inputs.
```

## Maintenance

Update this index when a document becomes a regular entry point for future
work, when its status changes meaningfully, or when a risky caveat needs to be
visible before reading.
