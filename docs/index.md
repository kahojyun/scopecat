# Document Index

## Purpose

Compact index of high-value docs for readers and future AI sessions. Stable
documentation policy belongs in [`README.md`](README.md).

If this index and a document's own status disagree, trust the document's own
status. Index descriptors are navigation labels, not validation statuses.

## Core Map

```text
docs/
  strategy/   project direction and adoption routes
  evidence/   evidence inventory, pain packets, interpretation method, research intake
  status/     compact coordination
```

## Index

| Document | Descriptor | Use For | Caveat |
| --- | --- | --- | --- |
| [`README.md`](README.md) | Stable policy | Documentation purpose, entry points, and editing rules. | Should stay compact and avoid current file inventory. |
| [`AGENTS.md`](AGENTS.md) | Stable policy | Always-applied AI instructions for work inside `docs/`. | Keep operational; do not move long background here. |
| [`strategy/vision.md`](strategy/vision.md) | Drafting project vision | Current product direction and boundaries: progressive adoption, explicit recording, complementing existing experiment systems, complexity ownership, and clear non-goals. | Not a roadmap, PRD, capability map, API/schema/UI/storage contract, or architecture decision. |
| [`strategy/adoption-routes.md`](strategy/adoption-routes.md) | Provisional route owner | Product-value route hypotheses grouped by user-visible payoff and behavior change. | Not a roadmap, capability map, implementation order, or product acceptance claim. |
| [`evidence/inventory.md`](evidence/inventory.md) | Evidence owner | Canonical evidence, lab/user context, top-level pains, pain/pressure rows, analysis options, anti-patterns, and saturation. | Interpretation rules belong in `evidence/method.md`; external references belong in `evidence/external-baseline.md`. |
| [`evidence/pain-packets/README.md`](evidence/pain-packets/README.md) | Pain packet index | Evidence-backed failure packets split by observed sample evidence, owner clarification, derived hypotheses, and premature scope. | Not validation charters, fixtures, product requirements, schemas, contracts, or architecture decisions. |
| [`evidence/method.md`](evidence/method.md) | Evidence method | Source confidence, bias correction, source-handling guardrails, prompt-method hygiene, design pressure handling, and external baseline interpretation. | Does not own evidence rows or accepted validation scope. |
| [`evidence/external-baseline.md`](evidence/external-baseline.md) | External baseline | Public framework references used to avoid false differentiation claims. | Recheck versions and access dates before using for published claims or implementation decisions. |
| [`status/progress-tracker.md`](status/progress-tracker.md) | Active tracker | Compact phase, link, and coordination surface. | Not a task queue, roadmap, or second backlog. |
| [`evidence/research/README.md`](evidence/research/README.md) | Stable research policy | Research directory purpose and promotion rule. | Does not define product direction. |
| [`evidence/research/research-index.md`](evidence/research/research-index.md) | Working research index | Current research inputs, extraction state, caveats, and retention rules. | Research entries are evidence inputs unless separately promoted. |

## Future Areas

Do not create directories only to match a taxonomy. Add these only when there
is durable content with a clear owner and purpose:

- `architecture/` for contracts, ADRs, and ownership decisions;
- `user/` for public, redacted MkDocs-facing documentation;

## Maintenance

Update this index when a document becomes a regular entry point for future
work, when its status changes meaningfully, or when a risky caveat needs to be
visible before reading.
