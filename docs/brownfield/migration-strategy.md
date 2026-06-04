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

## Current-To-Target Migration Model

Use the current-state work patterns as migration entry points, and use target
journeys as design validation boundaries. Actual adoption can start at whichever
entry point has the strongest local pain, but project design should keep the
Measurement Record and review/package boundaries coherent.

| Current Work Pattern | Migration Move | Target Boundary |
| --- | --- | --- |
| Making external runs visible | Record declared source posture, primary data, and context references without replacing the producing scripts or notebooks. | JNY-007 Record Or Adopt A Measurement; CAP-001 Measurement Records. |
| Selecting measurements for sharing | Select a complete-enough Measurement Record, export it, and keep open-before-import review separate from accepted import. | JNY-001 Share A Selected Measurement; CAP-002 Handoff Packages. |
| Checking context before a run | Compose review-ready parameter, code, environment, setup, and prior-context summaries, then record acknowledgement or deferral without run-start authority. | JNY-002 Prepare A Manual Run; CAP-003/CAP-004/CAP-005 support. |
| Maintaining parameter and setup files | Review, compare, and summarize parameter/registry/setup variants as capability evidence before promoting any standalone journey. | CAP-003 Parameter State Review; setup-binding support. |
| Checking instrument and service readiness | Capture bounded evidence or typed operation receipts while the old system remains the readiness authority. | CAP-004 Environment Operation; JNY-002/JNY-009 support. |
| Continuing calibration work | Record fit review, user action, continuation state, and accepted write handoff before considering execution assistance. | JNY-003 Recover Or Continue Calibration Work. |
| Inspecting running measurements | Observe lifecycle/progress/partial-data events without scan control or scheduling ownership. | JNY-004 Monitor A Running Measurement; CAP-006 candidate. |
| Reviewing completed results | Browse, filter, plot, and review primary data, derived artifacts, notes, and missing context before downstream handoff, comparison, or rerun preparation. | JNY-008 Browse And Review Completed Results. |
| Reconstructing a reference or rerun | Compare declared context and selected code context, then prepare rerun/reproduction evidence without claiming setup truth or execution authority. | JNY-009 Reproduce Or Rerun From A Reference; Experiment Code and Selected Reference support. |

This mapping is not an implementation order. It is the boundary map that keeps
current-state evidence, target journeys, and migration authority aligned.

## Migration Phases

### Coexist And Record

Scopecat works beside existing scripts, notebooks, workbooks, drivers, and
folders. It records declared facts, references, receipts, and review summaries
without requiring users to rewrite the producing workflow.

Examples:

- create a local Measurement Record shell from a user-selected run;
- record parameter, setup, code, artifact, or evidence references;
- capture a bounded environment-operation result;
- produce read-only package or record previews.

### Bridge Narrow Boundaries

Scopecat adapts selected legacy or external artifacts into one explicit
Scopecat boundary. The bridge must declare what it accepted, copied, converted,
omitted, or could not prove.

Examples:

- reviewed normalized primary data becomes durable Measurement Records data;
- selected Measurement Records export to a handoff package;
- adapter-authored parameter state becomes reviewed parameter-state storage;
- prepared-run review evidence becomes a receipt that a later Measurement
  Record can reference.

### Move Ownership One Boundary At A Time

Scopecat can become a partial owner only for a named boundary with accepted
behavior, failure handling, and non-claims. It should not expand from one
accepted mutation into adjacent authority by implication.

Examples:

- owning handoff package writing does not imply owning source measurement
  creation;
- owning parameter review does not imply hardware apply;
- owning running progress observation does not imply scan control;
- owning code-context recording does not imply dependency closure or execution
  readiness.

### Add Product-Native Capabilities After Coexistence

After the bridge boundaries are useful, Scopecat can add capabilities that are
hard to maintain in the current workflow, such as cross-run comparison,
parameter history, post-run results readiness review, reference-based rerun
preparation, calibration continuation state, and package receiving continuity.

These additions should still be pulled by named journeys or capability use
cases. They should not be introduced merely because a concept is adjacent to
the migrated data.

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
