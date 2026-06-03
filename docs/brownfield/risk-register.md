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

## Risk Levels

| Level | Meaning |
| --- | --- |
| High | Likely to cause unsafe ownership, data loss, misleading product scope, or blocked adoption if ignored. |
| Medium | Likely to cause rework, confusing UX, or validation drift if ignored. |
| Low | Worth watching but not currently shaping migration sequencing. |

## Register

| Risk | Level | Where It Shows Up | Mitigation Owner | Current Mitigation |
| --- | --- | --- | --- | --- |
| Hardware or run-start authority creep | High | Pre-run review, environment operation, calibration continuation, running monitor. | [`migration-strategy.md`](migration-strategy.md), [`../decisions/register.md`](../decisions/register.md) | Keep run start, hardware apply, scheduling, and recovery outside Scopecat unless a decision record moves the boundary. |
| Legacy parser creep | High | Measurement import, source observation, handoff package preparation. | [`transition-architecture.md`](transition-architecture.md), [`../discovery/routes/measurement-records/import-source-decision.md`](../discovery/routes/measurement-records/import-source-decision.md) | Use adapters and anti-corruption boundaries; do not parse arbitrary legacy sources in core. |
| Data loss or silent data transformation | High | Measurement Records import, package export/import, existing-record updates. | [`../engineering/workflow-validation-map.md`](../engineering/workflow-validation-map.md), prototype-boundary docs | Prefer explicit source identity, no-overwrite behavior, durable receipts, and missing-context warnings. |
| Portable/export redaction or reference leak | High | Handoff packages, export artifacts, review summaries carried outside the local workspace. | [`../discovery/policies/artifact-boundary-and-redaction.md`](../discovery/policies/artifact-boundary-and-redaction.md) | Classify portable/export boundaries and validate managed references before export. |
| Premature shared domain model extraction | High | Measurement context, parameter state, code context, setup binding, selected reference. | [`migration-roadmap.md`](migration-roadmap.md), [`../decisions/register.md`](../decisions/register.md) | Advance by vertical slice; extract shared models only after repeated slices need the same stable contract. |
| Journey/capability/use-case drift | Medium | Target journeys, workflow validation map, implementation register. | [`../traceability.md`](../traceability.md), [`../product/target-journeys.md`](../product/target-journeys.md) | Keep user journeys, use cases, capabilities, validation rows, and implementation owners linked explicitly. |
| Operator workflow mismatch | Medium | Pre-run context review, calibration continuation, running monitor, reference comparison. | [`current-state-assessment.md`](current-state-assessment.md), discovery problem briefs | Treat current state as sampled evidence; reopen discovery when real operator behavior does not match the modeled journey. |
| Over-formal pre-run approval UX | Medium | Pre-Run Context Review. | [`../product/target-journeys.md`](../product/target-journeys.md), [`transition-architecture.md`](transition-architecture.md) | Use acknowledgement, deferral, or note language; do not make Scopecat an approval or run-permission system. |
| Code/environment ownership expansion | Medium | Experiment Code Context, Environment Operation, Pre-Run Context Review. | [`../decisions/register.md`](../decisions/register.md), [`transition-architecture.md`](transition-architecture.md) | Treat code context and environment operation as supporting evidence unless a narrower workflow earns runtime or execution ownership. |
| Trust/authenticity overclaim | Medium | Handoff package open, import, source observation, external references. | [`migration-strategy.md`](migration-strategy.md), workflow validation map | Keep review, integrity observation, trust, authenticity, scientific validity, and accepted import separate. |
| Sampled current state mistaken for complete truth | Medium | Current-state assessment, target journey catalog, roadmap. | [`current-state-assessment.md`](current-state-assessment.md) | Record patterns, not exhaustive inventories; absence from current state does not mean the workflow or risk does not exist. |

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

Update this register when a risk level, mitigation owner, or mitigation rule
changes. Do not use it to track active work items; use issues, PRs, or
branch-specific notes for execution.
