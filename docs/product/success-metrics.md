# Success Metrics

## Status

Current product success metrics and adoption outcome guide.

## Purpose

Define how Scopecat adoption and brownfield modernization progress should be
judged.

Use this document when deciding whether a proposed capability, slice, or
hardening step improves the real workflow enough to justify promotion.

## Product Outcomes

Scopecat succeeds when it makes existing scientific measurement work easier to
record, inspect, select, hand off, compare, recover, or continue without
forcing users to replace working lab systems first.

Important outcomes:

- useful runs and records can be found without reconstructing context by hand;
- selected measurements can move across machines with less context loss;
- users can inspect before import, mutation, or organization;
- completed or partial results can be reviewed without hiding source identity;
- calibration or setup continuation uses reviewable evidence instead of
  notebook-local memory;
- code, parameter, setup, and environment context can be recorded or reviewed
  where that reduces real workflow friction;
- deeper runtime, driver, scan, service, or migration ownership is accepted
  only when a named workflow proves that lighter adapters, records, or review
  surfaces are not enough.

## Brownfield Constraints

Successful adoption preserves brownfield safety and continuity:

- existing experiment systems remain usable while Scopecat is adopted;
- Scopecat records, bridges, reviews, packages, or assists before it replaces;
- user review remains explicit before storage mutation, hardware action, or
  authority transfer;
- legacy folder shapes and private workflow residue do not silently become
  product domain models;
- current-state evidence can justify work, but accepted behavior belongs in
  journeys, decisions, engineering boundaries, and implementation owners.

## Journey Signals

### JNY-001 Share A Selected Measurement

Success signals:

- a complete-enough Measurement Record can be exported into a Scopecat-authored
  handoff package;
- the receiver can open and review the package before import;
- import remains explicit and separate from package inspection;
- package identity, primary data, linked context, and missing context stay
  visible without claiming sender trust, authenticity, or scientific validity.

Anti-signals:

- users must import before inspection;
- handoff starts owning post-run browsing, plotting, or readiness semantics;
- package fixtures or receipts recreate discovery-slice workflow envelopes.

### JNY-007 Record Runs

Success signals:

- externally produced, legacy-backed, adapter-authored, or manually declared
  run facts can become local Measurement Records without replacing the
  producing system;
- source identity, primary data, and context references are explicit;
- durable import and read-model refresh behavior reduce manual bookkeeping.

Anti-signals:

- raw legacy parsing becomes unbounded;
- Measurement Records claim scientific validity, hardware truth, or final
  public storage schema before those boundaries are accepted.

### JNY-008 Browse And Review Completed Results

Success signals:

- users can find, open, filter, plot, and review completed or near-completed
  results before deciding what to hand off, compare, continue, or rerun;
- primary data, derived artifacts, notes, missing context, and review decisions
  remain distinguishable;
- readiness review is owned outside handoff package mechanics.

Anti-signals:

- plots or reports are treated as complete record truth;
- browsing and readiness behavior hides inside JNY-001 handoff code;
- source identity and primary-data references disappear behind derived views.

### JNY-002/JNY-003/JNY-004/JNY-009 Supporting Work

Success signals:

- prepared-run context, calibration continuation, running-measurement
  inspection, and reference-based rerun work produce reviewable evidence before
  they claim execution or hardware authority;
- sealed prototype evidence stays historical unless a named brownfield
  entrypoint earns a live route.

Anti-signals:

- parameter, environment, code, monitor, or reference concepts are promoted
  from discovery fixtures without a real user path;
- run-start, live write-back, scheduling, or hardware apply authority expands
  by adjacency.

## Promotion Checks

Before promoting a capability or implementation owner, check:

- Which target journey or use case benefits?
- Which current-state pain or migration risk does it reduce?
- What authority does Scopecat gain, and what remains outside scope?
- Can the user inspect or review before mutation?
- Are contracts driven by durable workflow needs rather than discovery fixture
  shape?
- Are redaction and artifact-boundary requirements appropriate to the output?

## Product Anti-Metrics

The project is moving in the wrong direction when:

- users need more manual bookkeeping to satisfy Scopecat;
- users must replace working lab systems before seeing value;
- local path residue, notebooks, or copied folders become implicit product
  truth;
- handoff, recording, review, plotting, and import collapse into one workflow
  authority;
- shared domain models appear before multiple production-shaped routes prove
  stable concepts;
- public/export artifacts carry private paths, hostnames, lab identifiers, or
  unreviewed sensitive context;
- hardware control, scan execution, scheduling, or live write-back expands
  without explicit validation and decision records.

## Owners

Use these owner documents for details:

- [`../brownfield/current-state-assessment.md`](../brownfield/current-state-assessment.md)
  for current lab workflow and artifact reality;
- [`../brownfield/migration-strategy.md`](../brownfield/migration-strategy.md)
  for modernization patterns and authority-transfer rules;
- [`../brownfield/transition-architecture.md`](../brownfield/transition-architecture.md)
  for current/transition/target journey mapping;
- [`target-journeys.md`](target-journeys.md) for target journeys and use cases;
- [`target-capabilities.md`](target-capabilities.md) for capability maturity
  and advancement questions;
- [`adoption-strategy.md`](adoption-strategy.md) for user-facing adoption
  paths;
- [`../engineering/workflow-validation-map.md`](../engineering/workflow-validation-map.md)
  for engineering validation state.
