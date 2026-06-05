# Decisions

## Status

Decision-record navigation and governance.

## Purpose

Provide one flat entry point for durable Scopecat decisions. This directory
owns the decision taxonomy, the decision register, and the template for new
decision records.

Use this directory when a change needs to answer:

- whether a choice is a product, architecture, engineering, discovery, or
  operational decision;
- whether a decision is accepted, superseded, retired, or only proposed;
- what should trigger a future review or superseding decision.

Use [`register.md`](register.md) as the current index. Use
[`template.md`](template.md) when creating a new decision record.

Registered decision records live directly in this directory as
`DEC-*-short-title.md` files. Do not create type-specific subdirectories such
as `architecture/`, `product/`, or `engineering/`; keep the type in the record
metadata and register row instead. Do not assign a `DEC-*` ID to a decision that
only lives inside another source document.

## Decision Types

| Type | Use For |
| --- | --- |
| Architecture | System boundaries, integration patterns, authority transfer, shared models, execution/runtime/hardware ownership, storage or artifact architecture. |
| Product | Target journeys, adoption scope, deferred umbrella journeys, non-goals, user-facing product boundaries. |
| Engineering | Implementation strategy, prototype promotion, module boundary, test strategy, compatibility policy, live owner-local technical tradeoff. |
| Discovery | Discovery closeout, stop rule, reopen trigger, accepted-for-now evidence interpretation that has not yet become architecture, product, or engineering scope. |
| Operational | Development process, tooling, release, CI, package-management, or documentation workflow choices. |

## ADR Usage

ADR means Architecture Decision Record. Use `ADR` only for
architecture-affecting decisions. Do not call every product, discovery, or
engineering decision an ADR.

Create or update an architecture decision record when a branch:

- moves Scopecat toward hardware control, execution, scheduling, runtime,
  service, or write-back authority;
- extracts a shared domain model across capabilities;
- changes storage, package, artifact, or adapter architecture;
- replaces, retires, or becomes primary owner for a legacy path;
- changes trust, authenticity, redaction, or public/export artifact
  architecture.

## Lightweight Rule

Not every choice needs a new file or a `DEC-*` ID. If a decision is local to one
discovery track, prototype boundary, product map, module README, issue, or PR,
keep it in that source document without registering it here. Create and register a
standalone decision record when multiple owners need the decision or when
supersession history matters.

## Granularity Rule

Create or promote a `DEC-*` entry only when a branch accepts, rejects,
supersedes, or defers a durable product, architecture, engineering, discovery,
or operational boundary that future work must obey.

Prefer updating the active source document instead of creating a new decision when the
change only records:

- implementation sequencing, PR scope, or current milestone planning;
- validation status, next validation questions, or open advancement options;
- hardening checklists, review findings, or retry/error case inventory;
- wording clarification that does not change the accepted contract;
- source-local implementation detail already owned by a prototype-boundary or
  module README.

Roadmap and "what next" content belongs in the workflow validation map, product
capability map, prototype-boundary advancement questions, issues, PRs, or
branch-specific plans. Decision records should keep stable context, accepted
contract, scope, non-goals, consequences, alternatives, supersession, review
triggers, and related evidence.

## Update Rule

Update the register when a branch creates, supersedes, retires, or materially
changes a durable decision. Do not use this directory for task lists, open
questions without a decision, or validation evidence.

Keep the register as a compact index. During documentation cleanup, retire,
supersede, or move any remaining live guidance into the relevant source
document instead of adding summary columns or preserving decisions that no
longer guide future work.
