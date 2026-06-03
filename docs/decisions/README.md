# Decisions

## Status

Decision-record navigation and governance.

## Purpose

Provide one entry point for durable Scopecat decisions without moving every
historical decision document into one directory. This directory owns the
decision taxonomy, the decision register, and the template for new decision
records.

Use this directory when a change needs to answer:

- whether a choice is a product, architecture, engineering, discovery, or
  operational decision;
- where the current decision is recorded;
- whether a decision is accepted, superseded, retired, or only proposed;
- what should trigger a future review or superseding decision.

Use [`register.md`](register.md) as the current index. Use
[`template.md`](template.md) when creating a new decision record.

## Decision Types

| Type | Use For | Typical Owner |
| --- | --- | --- |
| Architecture | System boundaries, integration patterns, authority transfer, shared models, execution/runtime/hardware ownership, storage or artifact architecture. | `docs/decisions/architecture/` or the owning architecture document linked from the register. |
| Product | Target journeys, adoption scope, deferred umbrella journeys, non-goals, user-facing product boundaries. | `docs/decisions/product/` or the owning product document linked from the register. |
| Engineering | Implementation strategy, prototype promotion, module boundary, test strategy, compatibility policy, live route-local technical tradeoff. | `docs/decisions/engineering/` or the owning engineering document linked from the register. |
| Discovery | Discovery track closeout, stop rule, reopen trigger, accepted-for-now evidence interpretation. | Discovery route or slice owner linked from the register. |
| Operational | Development process, tooling, release, CI, package-management, or documentation workflow choices. | Project governance or tooling document linked from the register. |

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

Not every choice needs a new file. If a decision is local to one discovery
track, prototype boundary, or product map, keep the decision in that owner and
register it here. Create a new standalone decision record when multiple owners
need the decision or when supersession history matters.

## Update Rule

Update the register when a branch creates, supersedes, retires, or materially
changes a durable decision. Do not use this directory for task lists, open
questions without a decision, or validation evidence.
