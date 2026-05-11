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
| `progressive-adoption-progress-tracker.md` | Drafting | Tracking journey-first discovery, adoption ladders, migration wedges, contracts, and decision promotion. | Candidate ladders and wedges are unordered hypotheses, not priority commitments. |
| `research/README.md` | Stable policy | Research directory purpose and promotion rule. | Does not define product direction. |
| `research/AGENTS.md` | Stable policy | Always-applied AI instructions for work inside `docs/research/`. | Keeps raw research from being treated as product truth. |
| `research/research-index.md` | Working index | Current research inputs, extraction state, and caveats. | Research entries are evidence inputs unless separately promoted. |
| `research/greenfield-experimental-automation-architecture-notes.md` | Raw research input | Historical architecture vocabulary, candidate boundaries, and questions. | Contains first-direction and scaffold hypotheses; do not treat as current product plan. |
| `research/raw/fricon-legacy-docs/README.md` | Raw research input | Fricon predecessor docs, especially measurement-history analysis and long-term experiment-memory goals. | Fricon is replaced by this project; re-evaluate all claims under the broader capability model before promotion. |

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
