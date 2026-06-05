# ADR Register

## Purpose

Index accepted architecture decision records for Scopecat. This register is a
compact navigation and status index; rationale, scope, consequences,
alternatives, supersession, review triggers, and related evidence belong in the
linked ADR file.

Use stable `ADR-*` IDs when referencing architecture decisions from product,
brownfield, engineering, discovery, risk, source, or test documents.

## Active ADRs

| ID | Decision | Status |
| --- | --- | --- |
| ADR-0001 | [Use vertical-slice migration before shared model extraction](ADR-0001-vertical-slice-before-shared-model-extraction.md) | Accepted |
| ADR-0002 | [Use adapters and anti-corruption boundaries for legacy import/source handling](ADR-0002-import-source-anti-corruption-boundary.md) | Accepted |
| ADR-0003 | [Use post-run-first brownfield adoption for legacy measurement records](ADR-0003-post-run-first-brownfield-adoption.md) | Accepted |
| ADR-0004 | [Separate pre-run context review from run-start authority](ADR-0004-separate-pre-run-context-review-from-run-start-authority.md) | Accepted |
| ADR-0005 | [Keep experiment code context separate from runtime and execution ownership](ADR-0005-keep-experiment-code-context-separate-from-runtime-and-execution-ownership.md) | Accepted |
| ADR-0006 | [Use directory manifest packages for the JNY-001 production vertical slice path](ADR-0006-package-format-directory-manifest.md) | Accepted |
| ADR-0007 | [Treat JNY-001 directory packages as declared integrity evidence](ADR-0007-package-trust-authenticity-posture.md) | Accepted |
| ADR-0008 | [Package explicit linked context payloads without importing them](ADR-0008-linked-context-payload-packaging.md) | Accepted |
| ADR-0009 | [Allow batch import planning without batch durable mutation](ADR-0009-batch-receiving-import-planning.md) | Accepted |
| ADR-0010 | [Allow selected-record linked context payload export](ADR-0010-selected-record-linked-context-payload-export.md) | Accepted |
| ADR-0011 | [Allow selected-record batch package export without batch import](ADR-0011-selected-record-batch-package-export.md) | Accepted |
| ADR-0012 | [Defer linked context payload import](ADR-0012-defer-linked-context-payload-import.md) | Accepted |
| ADR-0013 | [Defer batch durable import](ADR-0013-defer-batch-durable-import.md) | Accepted |
| ADR-0014 | [Defer archive authority and archive-backed durable import](ADR-0014-defer-archive-authority-and-archive-backed-durable-import.md) | Accepted |
| ADR-0015 | [Accept safe archive materialization](ADR-0015-accept-safe-archive-materialization.md) | Accepted |
| ADR-0016 | [Accept safe archive creation](ADR-0016-accept-safe-archive-creation.md) | Accepted |
| ADR-0017 | [Defer existing-record update and final storage schema for JNY-001](ADR-0017-defer-existing-record-update-and-final-storage-schema.md) | Accepted |

## Update Rule

Update this register when a branch creates, supersedes, retires, renumbers, or
materially changes an ADR. Keep register rows compact; do not duplicate ADR
body content here.
