# Document Index

## Purpose

Compact index of high-value docs for readers and future AI sessions. Stable
documentation policy belongs in [`README.md`](README.md).

If this index and a document's own status disagree, trust the document's own
status. Index descriptors are navigation labels, not validation statuses.

## Core Map

```text
docs/
  strategy/   project direction, adoption routes, experience placement
  evidence/   evidence inventory plus research intake and extraction
  journeys/   JC-owned journeys, slices, decisions, contracts, prototypes
  standards/  durable process and review rules
  status/     compact cross-journey coordination
```

## Index

| Document | Descriptor | Use For | Caveat |
| --- | --- | --- | --- |
| [`README.md`](README.md) | Stable policy | Documentation purpose, entry points, and editing rules. | Should stay compact and avoid current file inventory. |
| [`AGENTS.md`](AGENTS.md) | Stable policy | Always-applied AI instructions for work inside `docs/`. | Keep operational; do not move long background here. |
| [`strategy/vision.md`](strategy/vision.md) | Drafting project vision | Current product direction and boundaries: progressive adoption, explicit recording, complementing existing experiment systems, complexity ownership, and clear non-goals. | Not a roadmap, PRD, capability map, API/schema/UI/storage contract, or architecture decision. |
| [`strategy/experience-map.md`](strategy/experience-map.md) | Drafting experience map | Complete-experience shape across journey candidates, experience-step labels, and journey coverage placement. | Not a `JC` owner, accepted product plan, roadmap, capability map, API/schema/UI/storage contract, or prototype scope. |
| [`evidence/inventory.md`](evidence/inventory.md) | Evidence owner | Canonical evidence, lab/user context, top-level pains, pain/pressure rows, adoption blockers, external-framework baselines, statement-kind separation, anti-patterns, and `JC` candidate rows. | Future `JC` process guidance belongs in the operating standard. |
| [`journeys/jc-001/README.md`](journeys/jc-001/README.md) | Accepted boundary entry point | Entry point and reading order for `JC-001`, including its accepted passive evidence-view slice. | Earned exemplar, not a folder template for future journey candidates. |
| [`journeys/jc-002/README.md`](journeys/jc-002/README.md) | Draft journey, validating prototype | Entry point for the selected-run analysis handoff journey and fixture-backed prototype. | Snapshot boundary is draft and not accepted; not a manifest schema, API contract, export format, storage design, or UI spec. |
| [`standards/jc-operating-standard.md`](standards/jc-operating-standard.md) | Doc ready operating standard | Repeatable `JC-###` status language, source-map gates, promotion flow, acceptance gates, conflict handling, and reopening rules. | Process owner only; use evidence owner docs for `EV-###`, `PN-###`, `TP-###`, and `JC-###` source material. |
| [`status/progress-tracker.md`](status/progress-tracker.md) | Active tracker | Compact phase, link, and cross-journey coordination surface. | Not a journey-local task queue or second backlog. |
| [`evidence/research/README.md`](evidence/research/README.md) | Stable research policy | Research directory purpose and promotion rule. | Does not define product direction. |
| [`evidence/research/research-index.md`](evidence/research/research-index.md) | Working research index | Current research inputs, extraction state, caveats, and retention rules. | Research entries are evidence inputs unless separately promoted. |

## Future Areas

Do not create directories only to match a taxonomy. Add these only when there
is durable content with a clear owner and purpose:

- `architecture/` for cross-journey contracts, ADRs, and ownership decisions;
- `user/` for public, redacted MkDocs-facing documentation;
- `strategy/adoption-routes.md` if adoption routes outgrow the tracker.

## Maintenance

Update this index when a document becomes a regular entry point for future
work, when its status changes meaningfully, or when a risky caveat needs to be
visible before reading.
