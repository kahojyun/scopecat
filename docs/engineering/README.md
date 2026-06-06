# Engineering Governance

## Status

Engineering governance navigation.

## Purpose

This directory owns cross-route engineering process rules after discovery
evidence starts moving toward implementation. It exists to prevent drift
between user journeys, workflows, use cases, product capabilities, validation
artifacts, and live implementation owners.

Use these documents before adding or promoting live code:

| Document | Use For |
| --- | --- |
| [`delivery-maturity-model.md`](delivery-maturity-model.md) | Classify maturity for user journeys, workflows, use cases, vertical slices, and product capabilities; choose validation methods without treating candidate/prototype counts as progress. |
| [`../product/target-journeys.md`](../product/target-journeys.md) | Find canonical target journeys, use cases, candidate use cases, and supporting workflows. |
| [`workflow-validation-map.md`](workflow-validation-map.md) | Find validation evidence, missing seams, and next validation questions for canonical use cases. |
| [`implementation-register.md`](implementation-register.md) | Track live implementation owners and route readers to module and prototype-boundary detail. |
| [`../product/target-capabilities.md`](../product/target-capabilities.md) | Track product capabilities, maturity, evidence state, and open advancement questions. |
| [`terminology.md`](terminology.md) | Use standard terms for workflows, capabilities, maturity, validation methods, decisions, evidence, artifact boundaries, and ownership. |
| [`prototype-boundaries/README.md`](prototype-boundaries/README.md) | Find current implementation-owner prototype boundaries and next decision gates. |
| [`pr-documentation-drift-checklist.md`](pr-documentation-drift-checklist.md) | Lightweight PR checklist for avoiding documentation drift without freezing future decisions. |

## Planning Inputs

Write issue, PR, or branch-specific plans only when work is actually starting.
Those plans should gather facts from the existing owners instead of creating a
new durable source of truth:

- journey/use-case index for the canonical user journey, use case, candidate
  use case, or supporting workflow;
- validation map for validated behavior, missing seam, and next validation
  question;
- target capability map for product capability maturity and advancement
  pressure;
- brownfield docs for current-state, transition-state, migration, or
  authority-transfer questions;
- implementation register for live module ownership;
- prototype-boundary notes and module READMEs for accepted contracts, API
  orientation, tests, fixtures, and artifact boundaries;
- brownfield pain points or owner-local evidence notes only as evidence, not as
  live implementation ownership.

Before promoting planning or validation material into a new decision, apply the
decision granularity rule in [`../adr/README.md`](../adr/README.md).
Roadmap questions, PR scope, hardening inventories, and review findings should
stay in the active owner unless they accept, reject, supersede, or defer a
durable boundary that future work must obey.

## Scope

Engineering governance defines the project-level rules for when narrower
owners should be created, updated, promoted, or left as historical evidence.
