# Decision Register

## Status

Current decision register.

## Purpose

Index durable Scopecat decisions across product, brownfield, engineering,
discovery, and architecture documents. This register is a navigation and status
owner; it does not duplicate full decision rationale.

Use stable `DEC-*` IDs when referencing decisions from product, brownfield,
engineering, discovery, or risk documents. A decision may later receive a fuller
ADR-style record, but the register ID remains the cross-document handle.

## Register

| ID | Decision | Type | Status | Current Owner | Related Risks | Scope | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| DEC-001 | Defer `Start And Complete A Measurement` as an umbrella journey | Product | Accepted | [`../product/target-journeys.md`](../product/target-journeys.md) | BR-RISK-001 | Target journey catalog and experiment lifecycle composition. | Keeps full experiment lifecycle visible without making Scopecat own run-start, execution, monitoring, recovery, and handoff together. |
| DEC-002 | Use vertical-slice migration before shared domain model extraction | Architecture | Accepted | [`../brownfield/migration-roadmap.md`](../brownfield/migration-roadmap.md), [`../discovery/synthesis/shared-model-extraction-deferral.md`](../discovery/synthesis/shared-model-extraction-deferral.md) | BR-RISK-005 | Cross-capability model extraction and migration sequencing. | Shared domain concepts remain deferred until repeated vertical slices need the same stable contract. |
| DEC-003 | Use adapters and anti-corruption boundaries for legacy import/source handling | Architecture / Discovery | Accepted for discovery guidance | [`../discovery/routes/measurement-records/import-source-decision.md`](../discovery/routes/measurement-records/import-source-decision.md), [`../brownfield/migration-strategy.md`](../brownfield/migration-strategy.md) | BR-RISK-002, BR-RISK-010 | Legacy source, adapter-normalized primary data, and source observation boundaries. | Core Scopecat should not parse arbitrary legacy systems without a later accepted decision. |
| DEC-004 | Use post-run-first brownfield adoption for legacy measurement records | Product / Discovery | Accepted for discovery guidance | [`../discovery/routes/measurement-records/legacy-brownfield-adoption-decision.md`](../discovery/routes/measurement-records/legacy-brownfield-adoption-decision.md), [`../brownfield/transition-architecture.md`](../brownfield/transition-architecture.md) | BR-RISK-002, BR-RISK-003, BR-RISK-010 | Low-intrusion Measurement Records adoption around existing runs. | During-run events remain future-compatible but not runner ownership. |
| DEC-005 | Keep calibration continuation review-only until a narrower workflow earns execution or write-back authority | Discovery / Product | Accepted for discovery guidance | [`../discovery/routes/calibration-continuation/decision.md`](../discovery/routes/calibration-continuation/decision.md), [`../product/target-journeys.md`](../product/target-journeys.md) | BR-RISK-001, BR-RISK-005, BR-RISK-007 | Calibration continuation, accepted write handoff, and parameter-state bridge. | Review actions are labels; hardware apply, scheduler, runner, and fitting execution remain deferred. |
| DEC-006 | Separate pre-run context review from run-start authority | Product / Architecture | Accepted | [`../product/target-journeys.md`](../product/target-journeys.md), [`../brownfield/transition-architecture.md`](../brownfield/transition-architecture.md) | BR-RISK-001, BR-RISK-007, BR-RISK-008, BR-RISK-009 | Pre-run context review, acknowledgement, and no-run-start boundary. | Operator acknowledgement is not experiment approval, execution permission, hardware safety, or automatic run start. |
| DEC-007 | Treat selected reference comparison as a review-oriented journey | Product | Accepted | [`../product/target-journeys.md`](../product/target-journeys.md), [`../brownfield/transition-architecture.md`](../brownfield/transition-architecture.md) | BR-RISK-007, BR-RISK-010 | Cross-journey comparison and objective findings. | Supports pre-run, post-run, calibration, monitoring, and handoff decisions without turning every comparison input into a new journey. |
| DEC-008 | Keep experiment code context separate from runtime and execution ownership | Product / Architecture | Accepted | [`../product/target-journeys.md`](../product/target-journeys.md), [`../brownfield/transition-architecture.md`](../brownfield/transition-architecture.md) | BR-RISK-005, BR-RISK-009 | Experiment code context recording, comparison, materialization, and readiness evidence. | Code context supports other journeys but does not imply Git replacement, package management, deployment, runtime, or experiment execution. |
| DEC-009 | Retire historical handoff discovery route decision as active guidance | Discovery | Retired | [`../discovery/archive/measurement-records-handoff-route/decision.md`](../discovery/archive/measurement-records-handoff-route/decision.md) | None active | Historical handoff package route discovery closeout. | Current handoff boundaries live in engineering prototype-boundary and module docs. |

## Unregistered Decision-Like Artifacts

These artifacts are decision pressure or recommendations, not durable decisions
unless a future branch promotes them:

| Artifact | Current Classification | Owner |
| --- | --- | --- |
| Selected Measurement Export Decision Summary | Decision-ready discovery summary, not ADR or product contract. | [`../discovery/slices/measurement-records/selected-measurement-export-decision-summary.md`](../discovery/slices/measurement-records/selected-measurement-export-decision-summary.md) |
| Scan Data Shape Decision Summary | Decision-ready discovery summary, not final data model. | [`../discovery/slices/measurement-records/scan-data-shape-decision-summary.md`](../discovery/slices/measurement-records/scan-data-shape-decision-summary.md) |

## Update Rule

Update this register when a branch creates, supersedes, retires, reclassifies,
or materially changes a durable decision. If an artifact is only recommendation
or discovery evidence, list it under unregistered decision-like artifacts
instead of promoting it implicitly.
