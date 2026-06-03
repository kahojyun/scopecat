# Brownfield Risk Register

## Status

Current brownfield risk register.

## Purpose

Track recurring brownfield risks that can derail Scopecat's migration strategy.
This is a risk register, not a task list, test plan, decision record, or
implementation backlog.

Use this register to keep high-risk boundaries visible while vertical slices
advance. Use decision records when a risk requires a durable choice, and use
issues or PRs for active mitigation work.

Use stable `BR-RISK-*` IDs when referencing risks from strategy, transition,
journey, validation, or decision documents. Risk titles may change for clarity;
IDs should not be reused.

Include governance risks only when they can directly change migration
sequencing, product ownership boundaries, data integrity, export safety, or
operator adoption. Do not use this register for ordinary documentation hygiene,
traceability upkeep, or process compliance issues.

## Risk Levels

| Level | Meaning |
| --- | --- |
| High | Likely to cause unsafe ownership, data loss, misleading product scope, or blocked adoption if ignored. |
| Medium | Likely to cause rework, confusing UX, or validation drift if ignored. |
| Low | Worth watching but not currently shaping migration sequencing. |

## Register

| ID | Risk | Type | Level | Where It Shows Up | Mitigation Owner | Current Mitigation |
| --- | --- | --- | --- | --- | --- | --- |
| BR-RISK-001 | Hardware or run-start authority creep | Migration / Product boundary | High | Pre-run review, environment operation, calibration continuation, running monitor. | [`migration-strategy.md`](migration-strategy.md), [`../decisions/register.md`](../decisions/register.md) | Keep run start, hardware apply, scheduling, and recovery outside Scopecat unless a decision record moves the boundary. |
| BR-RISK-002 | Legacy parser creep | Migration / Architecture | High | Measurement import, source observation, handoff package preparation. | [`transition-architecture.md`](transition-architecture.md), [`../discovery/routes/measurement-records/import-source-decision.md`](../discovery/routes/measurement-records/import-source-decision.md) | Use adapters and anti-corruption boundaries; do not parse arbitrary legacy sources in core. |
| BR-RISK-003 | Data loss or silent data transformation | Product / Data integrity | High | Measurement Records import, package export/import, existing-record updates. | [`../engineering/workflow-validation-map.md`](../engineering/workflow-validation-map.md), prototype-boundary docs | Prefer explicit source identity, no-overwrite behavior, durable receipts, and missing-context warnings. |
| BR-RISK-004 | Portable/export redaction or reference leak | Product / Artifact boundary | High | Handoff packages, export artifacts, review summaries carried outside the local workspace. | [`../discovery/policies/artifact-boundary-and-redaction.md`](../discovery/policies/artifact-boundary-and-redaction.md) | Classify portable/export boundaries and validate managed references before export. |
| BR-RISK-005 | Premature shared domain model extraction | Architecture / Migration | High | Measurement context, parameter state, code context, setup binding, selected reference. | [`migration-roadmap.md`](migration-roadmap.md), [`../decisions/register.md`](../decisions/register.md) | Advance by vertical slice; extract shared models only after repeated slices need the same stable contract. |
| BR-RISK-006 | Journey/capability/use-case drift | Migration governance | Medium | Target journeys, workflow validation map, implementation register. | [`../traceability.md`](../traceability.md), [`../product/target-journeys.md`](../product/target-journeys.md) | Keep user journeys, use cases, capabilities, validation rows, and implementation owners linked explicitly. |
| BR-RISK-007 | Operator workflow mismatch | Product adoption | Medium | Pre-run context review, calibration continuation, running monitor, reference comparison. | [`current-state-assessment.md`](current-state-assessment.md), discovery problem briefs | Treat current state as sampled evidence; reopen discovery when real operator behavior does not match the modeled journey. |
| BR-RISK-008 | Over-formal pre-run approval UX | Product UX | Medium | Pre-Run Context Review. | [`../product/target-journeys.md`](../product/target-journeys.md), [`transition-architecture.md`](transition-architecture.md) | Use acknowledgement, deferral, or note language; do not make Scopecat an approval or run-permission system. |
| BR-RISK-009 | Code/environment ownership expansion | Migration / Product boundary | Medium | Experiment Code Context, Environment Operation, Pre-Run Context Review. | [`../decisions/register.md`](../decisions/register.md), [`transition-architecture.md`](transition-architecture.md) | Treat code context and environment operation as supporting evidence unless a narrower workflow earns runtime or execution ownership. |
| BR-RISK-010 | Trust/authenticity overclaim | Product semantics | Medium | Handoff package open, import, source observation, external references. | [`migration-strategy.md`](migration-strategy.md), workflow validation map | Keep review, integrity observation, trust, authenticity, scientific validity, and accepted import separate. |
| BR-RISK-011 | Sampled current state mistaken for complete truth | Migration governance | Medium | Current-state assessment, target journey catalog, roadmap. | [`current-state-assessment.md`](current-state-assessment.md) | Record patterns, not exhaustive inventories; absence from current state does not mean the workflow or risk does not exist. |

## Review Triggers

Review this register when:

- a branch moves Scopecat closer to execution, hardware apply, scheduler,
  runtime, service, or write-back authority;
- a target journey, capability, or use case is added, split, merged, retired,
  or demoted;
- a portable/export artifact boundary changes;
- a vertical slice proposes shared model extraction;
- real current-state usage contradicts the modeled journey or transition path;
- a production vertical slice changes storage mutation, import, export, or
  rollback behavior.

## Update Rule

Update this register when a risk is added, retired, reclassified, or when its
level, mitigation owner, or mitigation rule changes. Do not use it to track
active work items; use issues, PRs, or branch-specific notes for execution.
