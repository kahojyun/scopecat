# Decision Register

## Purpose

Index durable Scopecat decisions across product, brownfield, engineering,
discovery, and architecture documents. This register is a compact navigation
and status owner; it does not duplicate rationale, scope, risk, or consequence
details from the decision record or owning document.

Use stable `DEC-*` IDs when referencing decisions from product, brownfield,
engineering, discovery, or risk documents. A decision may later receive a fuller
ADR-style record, but the register ID remains the cross-document handle.

## Active Decisions

| ID | Decision | Type | Status | Owner |
| --- | --- | --- | --- | --- |
| DEC-001 | Defer `Start And Complete A Measurement` as an umbrella journey | Product | Accepted | [`../product/target-journeys.md`](../product/target-journeys.md) |
| DEC-002 | Use vertical-slice migration before shared domain model extraction | Architecture | Accepted | [`architecture/DEC-002-vertical-slice-before-shared-model-extraction.md`](architecture/DEC-002-vertical-slice-before-shared-model-extraction.md), [`../brownfield/migration-roadmap.md`](../brownfield/migration-roadmap.md) |
| DEC-003 | Use adapters and anti-corruption boundaries for legacy import/source handling | Architecture | Accepted | [`architecture/DEC-003-import-source-anti-corruption-boundary.md`](architecture/DEC-003-import-source-anti-corruption-boundary.md), [`../brownfield/migration-strategy.md`](../brownfield/migration-strategy.md) |
| DEC-004 | Use post-run-first brownfield adoption for legacy measurement records | Architecture / Product | Accepted | [`architecture/DEC-004-post-run-first-brownfield-adoption.md`](architecture/DEC-004-post-run-first-brownfield-adoption.md), [`../brownfield/transition-architecture.md`](../brownfield/transition-architecture.md) |
| DEC-005 | Keep calibration continuation review-only until a narrower workflow earns execution or write-back authority | Architecture / Product | Accepted | [`architecture/DEC-005-calibration-continuation-review-only.md`](architecture/DEC-005-calibration-continuation-review-only.md), [`../product/target-journeys.md`](../product/target-journeys.md) |
| DEC-006 | Separate pre-run context review from run-start authority | Product / Architecture | Accepted | [`../product/target-journeys.md`](../product/target-journeys.md), [`../brownfield/transition-architecture.md`](../brownfield/transition-architecture.md) |
| DEC-007 | Treat selected reference comparison as a supporting review workflow | Product | Accepted | [`../product/target-journeys.md`](../product/target-journeys.md), [`../brownfield/transition-architecture.md`](../brownfield/transition-architecture.md) |
| DEC-008 | Keep experiment code context separate from runtime and execution ownership | Product / Architecture | Accepted | [`../product/target-journeys.md`](../product/target-journeys.md), [`../brownfield/transition-architecture.md`](../brownfield/transition-architecture.md) |
| DEC-010 | Use directory manifest packages for JNY-001 production vertical slice candidate | Architecture | Accepted | [`architecture/DEC-010-package-format-directory-manifest.md`](architecture/DEC-010-package-format-directory-manifest.md), [`../engineering/prototype-boundaries/handoff.md`](../engineering/prototype-boundaries/handoff.md) |
| DEC-011 | Treat JNY-001 directory packages as declared integrity evidence | Architecture | Accepted | [`architecture/DEC-011-package-trust-authenticity-posture.md`](architecture/DEC-011-package-trust-authenticity-posture.md), [`../engineering/prototype-boundaries/handoff.md`](../engineering/prototype-boundaries/handoff.md) |
| DEC-012 | Package explicit linked context payloads without importing them | Architecture | Accepted | [`architecture/DEC-012-linked-context-payload-packaging.md`](architecture/DEC-012-linked-context-payload-packaging.md), [`../engineering/prototype-boundaries/handoff.md`](../engineering/prototype-boundaries/handoff.md) |
| DEC-013 | Allow batch import planning without batch durable mutation | Architecture | Accepted | [`architecture/DEC-013-batch-receiving-import-planning.md`](architecture/DEC-013-batch-receiving-import-planning.md), [`../engineering/prototype-boundaries/handoff.md`](../engineering/prototype-boundaries/handoff.md) |
| DEC-014 | Allow selected-record linked context payload export | Architecture | Accepted | [`architecture/DEC-014-selected-record-linked-context-payload-export.md`](architecture/DEC-014-selected-record-linked-context-payload-export.md), [`../engineering/prototype-boundaries/handoff.md`](../engineering/prototype-boundaries/handoff.md) |
| DEC-015 | Allow selected-record batch package export without batch import | Architecture | Accepted | [`architecture/DEC-015-selected-record-batch-package-export.md`](architecture/DEC-015-selected-record-batch-package-export.md), [`../engineering/prototype-boundaries/handoff.md`](../engineering/prototype-boundaries/handoff.md) |
| DEC-016 | Defer linked context payload import | Architecture | Accepted | [`architecture/DEC-016-defer-linked-context-payload-import.md`](architecture/DEC-016-defer-linked-context-payload-import.md), [`../engineering/prototype-boundaries/handoff-durable-import-storage.md`](../engineering/prototype-boundaries/handoff-durable-import-storage.md) |
| DEC-017 | Defer batch durable import | Architecture | Accepted | [`architecture/DEC-017-defer-batch-durable-import.md`](architecture/DEC-017-defer-batch-durable-import.md), [`../engineering/prototype-boundaries/handoff-durable-import-storage.md`](../engineering/prototype-boundaries/handoff-durable-import-storage.md) |
| DEC-020 | Defer archive package implementation | Architecture | Accepted | [`architecture/DEC-020-defer-archive-package-implementation.md`](architecture/DEC-020-defer-archive-package-implementation.md), [`../engineering/prototype-boundaries/handoff.md`](../engineering/prototype-boundaries/handoff.md) |
| DEC-021 | Accept safe archive materialization | Architecture | Accepted | [`architecture/DEC-021-accept-safe-archive-materialization.md`](architecture/DEC-021-accept-safe-archive-materialization.md), [`../engineering/prototype-boundaries/handoff.md`](../engineering/prototype-boundaries/handoff.md) |
| DEC-024 | Accept safe archive creation | Architecture | Accepted | [`architecture/DEC-024-accept-safe-archive-creation.md`](architecture/DEC-024-accept-safe-archive-creation.md), [`../engineering/prototype-boundaries/handoff.md`](../engineering/prototype-boundaries/handoff.md) |
| DEC-025 | Defer existing-record update and final storage schema for JNY-001 | Architecture | Accepted | [`architecture/DEC-025-defer-existing-record-update-and-final-storage-schema.md`](architecture/DEC-025-defer-existing-record-update-and-final-storage-schema.md), [`../engineering/prototype-boundaries/handoff.md`](../engineering/prototype-boundaries/handoff.md) |

## Retired Decisions

| ID | Decision | Type | Status | Owner |
| --- | --- | --- | --- | --- |
| DEC-009 | Retire historical handoff discovery route decision as active guidance | Discovery | Retired | None active; Git history preserves the retired discovery note. |

## Update Rule

Update this register when a branch creates, supersedes, retires, reclassifies,
or materially changes a durable decision. Historical validation-slice pressure
that has not become a durable decision belongs in
[`../discovery/archive/slice-inventory.md`](../discovery/archive/slice-inventory.md)
or the current owner it informs, not in this register.

Do not add a new `DEC-*` entry for implementation sequencing, PR scope,
hardening inventory, review findings, validation status, next validation
questions, or wording-only cleanup. Keep those in the active workflow map,
product capability map, prototype-boundary advancement questions, issue, PR, or
branch plan unless they accept, reject, supersede, or defer a durable boundary
that future work must obey.

Keep register rows compact. Rationale, scope, related risks, notes,
consequences, alternatives, and review triggers belong in the decision record
or owning document linked from the row.

Prefer periodic cleanup over register expansion. When an active decision no
longer guides future work, retire it, supersede it, or fold the live rule into
the owning document instead of preserving stale active rows for completeness.
