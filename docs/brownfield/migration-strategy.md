# Brownfield Migration Strategy

## Status

Current brownfield migration strategy.

## Purpose

Define how Scopecat should migrate around existing lab systems without forcing
a rewrite.

Use this document when deciding whether a slice should bridge, shadow, assist,
replace, or retire a legacy path. Use
[`../product/target-journeys.md`](../product/target-journeys.md) for the
canonical journey/use-case index,
[`transition-architecture.md`](transition-architecture.md) for current pattern
to transition-boundary posture, and
[`migration-roadmap.md`](migration-roadmap.md) for design-validation sequence.

## Strategy

Scopecat should use incremental modernization around stable product value, not
a project-wide replacement plan.

The default approach is:

1. let the existing experiment workflow keep running;
2. observe or record current behavior beside it;
3. create a narrow Scopecat-owned record, review, package, receipt, or
   reference boundary;
4. bridge legacy artifacts into that boundary explicitly;
5. let users review before mutation;
6. promote one named use case when the user workflow is clear;
7. replace or retire a legacy path only after an explicit decision.

The first migration goal is continuity, not replacement. Scopecat should make
current work easier to inspect, preserve, select, hand off, and compare before
it tries to own execution, hardware control, runtime, or broad storage truth.

## Migration Phases

### Coexist And Record

Scopecat works beside existing scripts, notebooks, workbooks, drivers, and
folders. It records declared facts, references, receipts, and review summaries
without requiring users to rewrite the producing workflow.

Examples include creating a Measurement Record shell from a selected run,
recording parameter/setup/code/artifact references, capturing bounded
environment-operation evidence, and producing read-only package or record
previews.

### Bridge Narrow Boundaries

Scopecat adapts selected legacy or external artifacts into one explicit
Scopecat boundary. The bridge must declare what it accepted, copied,
converted, omitted, or could not prove.

Examples include reviewed normalized primary data becoming durable Measurement
Records data, selected Measurement Records becoming handoff packages, adapter
authored parameter state becoming reviewed parameter-state storage, and
prepared-run review evidence becoming a receipt that a later Measurement
Record can reference.

### Move Ownership One Boundary At A Time

Scopecat can become a partial owner only for a named boundary with accepted
behavior, failure handling, and non-claims. It should not expand from one
accepted mutation into adjacent authority by implication.

Owning package writing does not imply owning measurement creation. Owning
parameter review does not imply hardware apply. Owning progress observation
does not imply scan control. Owning code-context recording does not imply
dependency closure or execution readiness.

### Add Product-Native Capabilities After Coexistence

After bridge boundaries are useful, Scopecat can add capabilities that are
hard to maintain in the current workflow, such as cross-run comparison,
parameter history, post-run results readiness review, reference-based rerun
preparation, calibration continuation state, and package receiving continuity.

These additions should be pulled by named journeys or capability use cases.
They should not be introduced merely because a concept is adjacent to migrated
data.

## Migration Patterns

| Pattern | Use When | Avoid When |
| --- | --- | --- |
| Strangler Fig | Current work is valuable but hard to inspect, move, or recover; a product journey can improve the workflow without owning execution. | The slice silently depends on parsing arbitrary legacy artifacts or implies hardware-control ownership. |
| Adapter / Anti-Corruption Layer | Legacy artifacts contain useful facts but are not trustworthy product models; a bridge can declare what it copied, converted, omitted, or could not prove. | The adapter becomes an unbounded legacy parser or legacy folders become the product domain model. |
| Parallel Run / Shadow Mode | Correctness or safety must be established before authority moves; users need comparison evidence before adopting mutation. | Users might mistake shadow output for authoritative hardware state or the system cannot explain ownership. |
| Bridge | A target journey needs a useful intermediate state with preserved source identity and explicit review/import authority. | The bridge hides transformation decisions or accepting bridge output implies trust or scientific validity. |
| Assist | Users benefit from a bounded operation, readiness check, generated artifact, or typed receipt while retaining final authority. | The operation controls hardware, scheduling, or run start by default. |
| Retirement | A named Scopecat boundary has become the primary owner and the old path is no longer needed for the named workflow. | Production ownership, migration behavior, rollback expectations, or ADR coverage is missing. |

## Default Authority Rules

- Existing systems own hardware control, timing, live parameter application,
  trusted execution, emergency recovery, raw historical semantics, and
  scientific validity by default.
- Scopecat can own records, packages, receipts, reviews, previews, declared
  context, generated artifacts, and explicit adapters.
- Scopecat can move toward execution, driver, scan, service, runtime, or
  scheduling authority only after a narrower validated workflow and explicit
  decision.
- Shared domain model extraction should remain deferred until repeated
  production vertical slices prove stable cross-capability concepts.

## ADR Triggers

Create or update an ADR when a branch:

- moves a boundary from `Review`, `Bridge`, `Shadow`, or `Assist` to
  `Primary owner`;
- replaces or retires a legacy path;
- expands Scopecat into hardware apply, live write-back, scan execution,
  scheduling, remote execution, or service lifecycle ownership;
- promotes a legacy-specific artifact shape into a target product object;
- extracts a shared domain model across capabilities.

Use [`../adr/README.md`](../adr/README.md) only when the branch accepts,
defers, supersedes, or retires an architecture boundary that future work must
obey.

## Update Rule

Update this strategy when migration patterns, default authority rules, or ADR
triggers change.

Do not use this file as a roadmap, target journey map, implementation
checklist, or validation result.
