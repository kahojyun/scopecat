# Document Index

## Purpose

Compact index of high-value docs for readers and future AI sessions. This file
is allowed to change as the documentation set changes; stable documentation
policy belongs in `README.md`.

If this index and a document's own status disagree, trust the document's own
status.

## Index

| Document | Status | Use For | Caveat |
| --- | --- | --- | --- |
| `README.md` | Stable policy | Documentation purpose, entry points, and editing rules. | Should stay compact and avoid current file inventory. |
| `AGENTS.md` | Stable policy | Always-applied AI instructions for work inside `docs/`. | Keep operational; do not move long background here. |
| `progressive-adoption-progress-tracker.md` | Active tracker | Tracking journey-first discovery, adoption ladders, migration wedges, contracts, and decision promotion. | `JC-001` now has an accepted passive evidence-view decision; broader subsystem ideas remain hypotheses until promoted by later decisions. |
| `evidence-and-pain-point-inventory.md` | Ready as W1 evidence owner | W1 owner for evidence, lab/user context, top-level pain narratives, pain/pressure rows, adoption blockers, external-framework baselines, statement-kind separation, and first-fixture source-map requirements. | `JC-001` has been promoted out of this inventory; use `jc-001/README.md` for the first-wedge document set. |
| `jc-001/README.md` | Active first-wedge record | Entry point, reading order, and reusable document pattern for the first accepted `JC-001` wedge. | Use the local README before opening individual `JC-001` notes. |
| `research/README.md` | Stable policy | Research directory purpose and promotion rule. | Does not define product direction. |
| `research/AGENTS.md` | Stable policy | Always-applied AI instructions for work inside `docs/research/`. | Keeps raw research from being treated as product truth. |
| `research/research-index.md` | Working index | Current research inputs, extraction state, and caveats. | Research entries are evidence inputs unless separately promoted. |
| `research/extracted/research-acceptance-readiness-triage.md` | Transitional | Preferred entry point for deciding which raw research claims are accepted guardrails, evidence, inferences, hypotheses, future pressure, ADR-gated items, or rejected first-slice directions. | Keep through W2 validation, then delete or archive after useful claims move into narrower owner docs. |
| `research/extracted/legacy-experiment-code-sample-validation.md` | Transitional | Validation of the raw research triage against two copied legacy experiment code trees; use for concrete evidence on companion artifacts, settings drift, analysis handoff, hardware bring-up, dependency pain, notebook hygiene, and portability pressure. | Keep through W2 validation, then delete or archive after validation cases move into journey fixtures, capability/adoption hypotheses, architecture questions, or ADR triggers. |
| `research/greenfield-experimental-automation-architecture-notes.md` | Quarantined | Automation architecture pressure, historical vocabulary, candidate boundaries, and questions. | Preserve capability pressure beyond Measurement History, but do not use as a product plan, implementation order, or subsystem scaffold. |
| `research/raw/fricon-legacy-docs/README.md` | Extracting research input | Predecessor project documentation snapshot, especially measurement-history analysis and long-term experiment-memory goals. | Scopecat replaces the predecessor direction; use the extracted triage first. After W1, return to raw predecessor material only for exact examples, citations, or W2 fixtures. |

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
