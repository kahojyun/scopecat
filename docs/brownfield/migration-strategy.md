# Brownfield Migration Strategy

## Status

Current brownfield migration strategy.

## Purpose

Define how Scopecat should migrate around existing lab systems without forcing
a rewrite. This is a modernization strategy document, not a current-state
inventory, target journey map, implementation plan, or issue tracker.

Use this document when deciding whether a slice should bridge, shadow, assist,
replace, or retire a legacy path.

## Strategy

Scopecat should use incremental modernization around stable product value, not
a project-wide replacement plan.

The default approach is:

1. observe or record current behavior;
2. create a narrow Scopecat-owned boundary;
3. bridge legacy artifacts into that boundary explicitly;
4. let users review before mutation;
5. promote one vertical slice when the user workflow is clear;
6. replace or retire a legacy path only after an explicit decision.

## Migration Patterns

### Strangler Fig

Build Scopecat-owned records, packages, reviews, and adapters around existing
workflows. Move authority one boundary at a time instead of rewriting the
measurement stack.

Use when:

- current work is valuable but hard to inspect, move, or recover;
- a product journey can improve the workflow without owning execution;
- the replacement boundary is smaller than the existing system.

Avoid when:

- the slice silently depends on parsing arbitrary legacy artifacts;
- the boundary would imply hardware-control ownership without a decision.

### Adapter / Anti-Corruption Layer

Use explicit adapters to translate legacy/system artifacts into Scopecat-owned
records, packages, receipts, or review models. Keep legacy naming, file layout,
and implicit semantics out of target product object names.

Use when:

- current files contain useful facts but are not trustworthy product models;
- a bridge can declare what it copied, converted, omitted, or could not prove;
- source identity and missing context matter.

Avoid when:

- the adapter becomes an unbounded legacy parser;
- legacy folders become the product domain model.

### Parallel Run / Shadow Mode

Let Scopecat observe, compute, compare, or review beside the current path while
the legacy path remains authoritative.

Use when:

- correctness or safety must be established before authority moves;
- users need comparison evidence before adopting mutation;
- hardware or scientific validity remains outside Scopecat.

Avoid when:

- users might mistake shadow output for authoritative hardware state;
- the system cannot explain which path owns the final decision.

### Bridge

Bridge from a current artifact or workflow into a Scopecat-owned boundary such
as a Measurement Record, Handoff Package, parameter-state record, or review
receipt.

Use when:

- a target journey needs a useful intermediate state;
- the bridge can preserve source identity and declare missing context;
- review or import authority remains explicit.

Avoid when:

- the bridge hides transformation decisions;
- accepting bridge output implies trust, authenticity, or scientific validity.

### Assist

Let Scopecat help prepare or perform user-directed work without owning final
mutation or execution authority.

Use when:

- users benefit from a bounded operation, readiness check, or generated review
  artifact;
- the user remains responsible for applying the result;
- the operation can produce a typed receipt.

Avoid when:

- the operation controls hardware, scheduling, or run start by default;
- failure handling would require owning lab safety or recovery.

### Retirement

Retire a legacy path only when a named Scopecat boundary has become the primary
owner and the old path is no longer needed for the named workflow.

Retirement requires:

- a named target journey or use case;
- production-ready ownership for the boundary being retired;
- data or context migration behavior for needed history;
- explicit decision record;
- rollback or recovery expectations where user risk remains.

## Default Authority Rules

- Existing systems own hardware control, timing, live parameter application,
  trusted execution, emergency recovery, raw historical semantics, and
  scientific validity by default.
- Scopecat can own records, packages, receipts, reviews, previews, declared
  context, generated artifacts, and explicit adapters.
- Scopecat can move toward execution, driver, scan, service, or runtime
  authority only after a narrower validated workflow and explicit decision.
- Shared domain model extraction should remain deferred until repeated
  production vertical slices prove stable cross-capability concepts.

## Decision-Record Triggers

Create or update a decision record when a branch:

- moves a boundary from `Review`, `Bridge`, `Shadow`, or `Assist` to
  `Primary owner`;
- replaces or retires a legacy path;
- expands Scopecat into hardware apply, live write-back, scan execution,
  scheduling, remote execution, or service lifecycle ownership;
- promotes a legacy-specific artifact shape into a target product object;
- extracts a shared domain model across capabilities.

Use [`../decisions/README.md`](../decisions/README.md) to decide whether the
record is an architecture decision record, product decision, engineering
decision, discovery decision, or operational decision.

## Update Rule

Update this strategy when migration patterns, default authority rules, or
decision-record triggers change.

Do not use this file as a roadmap, backlog, implementation checklist, or
validation result.
