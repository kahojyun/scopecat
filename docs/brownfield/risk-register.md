# Brownfield Risk Register

## Status

Current brownfield risk register.

## Purpose

Track recurring brownfield risks that can derail Scopecat's migration strategy.

Use this register to keep high-risk boundaries visible as named use cases
advance. Use ADRs when a risk requires a durable architecture choice, and use
issues or PRs for active mitigation work.

Use stable `BR-RISK-*` IDs when referencing risks from strategy, transition,
journey, validation, or decision documents. Risk titles may change for clarity;
IDs should not be reused.

Include governance risks only when they can directly change migration
sequencing, product ownership boundaries, data integrity, export safety, or
operator adoption. Do not use this register for ordinary documentation hygiene,
cross-reference upkeep, or process compliance issues.

## Risk Levels

| Level | Meaning |
| --- | --- |
| High | Likely to cause unsafe ownership, data loss, misleading product scope, or blocked adoption if ignored. |
| Medium | Likely to cause rework, confusing UX, or validation drift if ignored. |
| Low | Worth watching but not currently shaping migration sequencing. |

## Register

| ID | Risk | Type | Level | Where It Shows Up | Related Decisions | Mitigation Owner | Current Mitigation |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BR-RISK-001 | Hardware or run-start authority creep | Migration / Product boundary | High | Pre-run review, environment operation, calibration continuation, running monitor. | ADR-0004 | [`migration-strategy.md`](migration-strategy.md), [`../adr/register.md`](../adr/register.md) | Keep run start, hardware apply, scheduling, and recovery outside Scopecat unless an ADR moves the boundary. |
| BR-RISK-002 | Legacy parser creep | Migration / Architecture | High | Measurement import, source observation, handoff package preparation. | ADR-0002, ADR-0003 | [`transition-architecture.md`](transition-architecture.md), [`../adr/ADR-0002-import-source-anti-corruption-boundary.md`](../adr/ADR-0002-import-source-anti-corruption-boundary.md) | Use adapters and anti-corruption boundaries; do not parse arbitrary legacy sources in core. |
| BR-RISK-003 | Data loss or silent data transformation | Product / Data integrity | High | Measurement Records import, package export/import, existing-record updates. | ADR-0003 | [`../engineering/workflow-validation-map.md`](../engineering/workflow-validation-map.md), prototype-boundary docs | Prefer explicit source identity, no-overwrite behavior, durable receipts, and missing-context warnings. |
| BR-RISK-004 | Portable/export redaction or reference leak | Product / Artifact boundary | High | Handoff packages, export artifacts, review summaries carried outside the local workspace. | None active | [`../architecture/artifact-boundary-and-redaction.md`](../architecture/artifact-boundary-and-redaction.md) | Classify portable/export boundaries and validate managed references before export. |
| BR-RISK-005 | Premature shared domain model extraction | Architecture / Migration | High | Measurement context, parameter state, code context, setup binding, selected reference. | ADR-0001, ADR-0005 | [`migration-roadmap.md`](migration-roadmap.md), [`../adr/register.md`](../adr/register.md) | Advance by named use cases; extract shared models only after repeated use cases need the same stable contract. |
| BR-RISK-006 | Journey/capability/use-case drift | Migration governance | Medium | Journey/use-case index, workflow validation map, capability map, implementation register. | None active | [`../product/target-journeys.md`](../product/target-journeys.md), [`../engineering/workflow-validation-map.md`](../engineering/workflow-validation-map.md), [`../engineering/implementation-register.md`](../engineering/implementation-register.md) | Keep canonical journeys/use cases, validation evidence, capability maturity, and implementation owners in their separate owner documents. |
| BR-RISK-007 | Operator workflow mismatch | Product adoption | Medium | Prepare a manual run, calibration continuation, running monitor, reference-based rerun, post-run results review. | ADR-0004 | [`current-state-assessment.md`](current-state-assessment.md), discovery problem briefs | Treat current state as sampled evidence; reopen discovery when real operator behavior does not match the modeled journey. |
| BR-RISK-008 | Over-formal pre-run approval UX | Product UX | Medium | Prepare A Manual Run. | ADR-0004 | [`../product/target-journeys.md`](../product/target-journeys.md), [`transition-architecture.md`](transition-architecture.md) | Use acknowledgement, deferral, or note language; do not make Scopecat an approval or run-permission system. |
| BR-RISK-009 | Code/environment ownership expansion | Migration / Product boundary | Medium | Experiment Code Context, Environment Operation, Prepare A Manual Run, Reproduce Or Rerun From A Reference. | ADR-0004, ADR-0005 | [`../adr/register.md`](../adr/register.md), [`transition-architecture.md`](transition-architecture.md) | Treat code context and environment operation as supporting evidence unless a narrower workflow earns runtime or execution ownership. |
| BR-RISK-010 | Trust/authenticity overclaim | Product semantics | Medium | Handoff package open, import, source observation, external references. | ADR-0002, ADR-0003 | [`migration-strategy.md`](migration-strategy.md), [`../engineering/workflow-validation-map.md`](../engineering/workflow-validation-map.md) | Keep review, integrity observation, trust, authenticity, scientific validity, and accepted import separate. |
| BR-RISK-011 | Sampled current state mistaken for complete truth | Migration governance | Medium | Current-state assessment, journey/use-case index, roadmap. | None active | [`current-state-assessment.md`](current-state-assessment.md), [`../product/target-journeys.md`](../product/target-journeys.md) | Record patterns, not exhaustive inventories; absence from current state does not mean the workflow or risk does not exist. |
| BR-RISK-012 | External file observation mistaken for backup | Product / Data integrity | Medium | Source observation, external references, shared lab paths, package materialization. | ADR-0002 | [`../adr/ADR-0002-import-source-anti-corruption-boundary.md`](../adr/ADR-0002-import-source-anti-corruption-boundary.md) | Treat observed file state as drift evidence only; require an explicit snapshot, managed copy, archive, or backup decision before claiming restore. |

## Review Triggers

Review this register when:

- a branch moves Scopecat closer to execution, hardware apply, scheduler,
  runtime, service, or write-back authority;
- a target journey, capability, or use case is added, split, merged, retired,
  or demoted;
- a portable/export artifact boundary changes;
- a named use case proposes shared model extraction;
- real current-state usage contradicts the modeled journey or transition path;
- a production vertical slice changes storage mutation, import, export, or
  rollback behavior.
- source observation starts recording stronger file state, snapshots, or shared
  storage assumptions.

## Update Rule

Update this register when a risk is added, retired, reclassified, or when its
level, mitigation owner, or mitigation rule changes. Do not use it to track
active work items; use issues, PRs, or branch-specific notes for execution.
