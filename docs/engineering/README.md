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
| [`workflow-validation-map.md`](workflow-validation-map.md) | Start from user journeys, use cases, scenarios, operations, validated behavior, missing seams, and next validation questions. |
| [`implementation-register.md`](implementation-register.md) | Track live implementation owners and route readers to module and prototype-boundary detail. |
| [`../product/target-capabilities.md`](../product/target-capabilities.md) | Track product capabilities, maturity, evidence state, and open advancement questions. |
| [`terminology.md`](terminology.md) | Use standard terms for workflows, capabilities, maturity, validation methods, decisions, evidence, artifact boundaries, and ownership. |
| [`prototype-boundaries/README.md`](prototype-boundaries/README.md) | Find current route-local engineering prototype boundaries and next decision gates. |
| [`pr-documentation-drift-checklist.md`](pr-documentation-drift-checklist.md) | Lightweight PR checklist for avoiding documentation drift without freezing future decisions. |

## Planning Inputs

Write issue, PR, or branch-specific plans only when work is actually starting.
Those plans should gather facts from the existing owners instead of creating a
new durable source of truth:

- workflow and use case map for the user journey, use case, scenario, operation,
  validated behavior, missing seam, and next validation question;
- target capability map for product capability maturity and advancement
  pressure;
- brownfield docs for current-state, transition-state, migration, or
  authority-transfer questions;
- implementation register for live module ownership;
- prototype-boundary notes and module READMEs for accepted contracts, API
  orientation, tests, fixtures, and artifact boundaries;
- discovery docs only as evidence, not as live implementation ownership.

Before promoting planning or validation material into a new decision, apply the
decision granularity rule in [`../decisions/README.md`](../decisions/README.md).
Roadmap questions, PR scope, hardening inventories, and review findings should
stay in the active owner unless they accept, reject, supersede, or defer a
durable boundary that future work must obey.

## Historical Reference

Use [`archive/README.md`](archive/README.md) only when an active owner points to
retired prototype plans, readiness checkpoints, or historical engineering
decisions.

## Boundary

This directory does not replace:

- product direction, target journey, target capability, or adoption-strategy
  docs;
- brownfield current-state, transition architecture, migration strategy, or
  migration roadmap docs;
- issue, PR, or branch-specific execution plans;
- discovery validation plans or results;
- route-specific prototype boundary notes;
- module READMEs that own live API details;
- public user documentation.

It defines the project-level rules for when those narrower owners should be
created, updated, promoted, or left as historical evidence.

Artifact/export boundary labels belong on generated fixtures, expected outputs,
review artifacts, packages, public docs, or other generated artifacts only when
they are part of a validation, review, portable/export, or public boundary.
They are not required for ordinary internal engineering governance documents in
this directory.
