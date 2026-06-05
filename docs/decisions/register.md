# Decision Register

## Purpose

Index durable Scopecat decisions across product, brownfield, engineering,
discovery, and architecture documents. This register is a compact navigation
and status index; it does not duplicate rationale, scope, risk, or consequence
details from the decision record.

Use stable `DEC-*` IDs when referencing decisions from product, brownfield,
engineering, discovery, or risk documents. Each registered `DEC-*` entry has a
standalone record in this flat directory; the register ID remains the
cross-document handle.

## Active Decisions

| ID | Decision | Type | Status |
| --- | --- | --- | --- |
| DEC-001 | [Defer `Start And Complete A Measurement` as an umbrella journey](DEC-001-defer-start-and-complete-a-measurement-umbrella-journey.md) | Product | Accepted |
| DEC-002 | [Use vertical-slice migration before shared domain model extraction](DEC-002-vertical-slice-before-shared-model-extraction.md) | Architecture | Accepted |
| DEC-003 | [Use adapters and anti-corruption boundaries for legacy import/source handling](DEC-003-import-source-anti-corruption-boundary.md) | Architecture | Accepted |
| DEC-004 | [Use post-run-first brownfield adoption for legacy measurement records](DEC-004-post-run-first-brownfield-adoption.md) | Architecture / Product | Accepted |
| DEC-005 | [Keep calibration continuation review-only until a narrower workflow earns execution or write-back authority](DEC-005-calibration-continuation-review-only.md) | Architecture / Product | Accepted |
| DEC-006 | [Separate pre-run context review from run-start authority](DEC-006-separate-pre-run-context-review-from-run-start-authority.md) | Product / Architecture | Accepted |
| DEC-008 | [Keep experiment code context separate from runtime and execution ownership](DEC-008-keep-experiment-code-context-separate-from-runtime-and-execution-ownership.md) | Product / Architecture | Accepted |
| DEC-010 | [Use directory manifest packages for the JNY-001 production vertical slice path](DEC-010-package-format-directory-manifest.md) | Architecture | Accepted |
| DEC-011 | [Treat JNY-001 directory packages as declared integrity evidence](DEC-011-package-trust-authenticity-posture.md) | Architecture | Accepted |
| DEC-012 | [Package explicit linked context payloads without importing them](DEC-012-linked-context-payload-packaging.md) | Architecture | Accepted |
| DEC-013 | [Allow batch import planning without batch durable mutation](DEC-013-batch-receiving-import-planning.md) | Architecture | Accepted |
| DEC-014 | [Allow selected-record linked context payload export](DEC-014-selected-record-linked-context-payload-export.md) | Architecture | Accepted |
| DEC-015 | [Allow selected-record batch package export without batch import](DEC-015-selected-record-batch-package-export.md) | Architecture | Accepted |
| DEC-016 | [Defer linked context payload import](DEC-016-defer-linked-context-payload-import.md) | Architecture | Accepted |
| DEC-017 | [Defer batch durable import](DEC-017-defer-batch-durable-import.md) | Architecture | Accepted |
| DEC-020 | [Defer archive package implementation](DEC-020-defer-archive-package-implementation.md) | Architecture | Accepted |
| DEC-021 | [Accept safe archive materialization](DEC-021-accept-safe-archive-materialization.md) | Architecture | Accepted |
| DEC-024 | [Accept safe archive creation](DEC-024-accept-safe-archive-creation.md) | Architecture | Accepted |
| DEC-025 | [Defer existing-record update and final storage schema for JNY-001](DEC-025-defer-existing-record-update-and-final-storage-schema.md) | Architecture | Accepted |

## Update Rule

Update this register when a branch creates, supersedes, retires, reclassifies,
or materially changes a durable decision. Historical validation-slice pressure
that has not become a durable decision belongs in
[`../discovery/archive/slice-inventory.md`](../discovery/archive/slice-inventory.md)
or the current source document it informs, not in this register.

Do not add a new `DEC-*` entry for implementation sequencing, PR scope,
hardening inventory, review findings, validation status, next validation
questions, or wording-only cleanup. Keep those in the active workflow map,
product capability map, prototype-boundary advancement questions, issue, PR, or
branch plan unless they accept, reject, supersede, or defer a durable boundary
that future work must obey.

Keep register rows compact. Rationale, scope, related risks, notes,
consequences, alternatives, and review triggers belong in the decision record
linked from the row.

Prefer periodic cleanup over register expansion. When an active decision no
longer guides future work, retire it, supersede it, or move any remaining live
guidance into the relevant source document instead of preserving stale active
rows for completeness.
