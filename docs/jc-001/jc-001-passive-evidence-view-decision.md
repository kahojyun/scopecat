# JC-001 Passive Evidence View Decision

## Status

Accepted on 2026-05-12.

## Decision

Scopecat accepts the first `JC-001` product wedge as a passive evidence-view
boundary:

```text
existing work bundle
  -> static artifact-role inventory
  -> evidence relations
  -> conflict and missing-fact report
  -> sharing-safe evidence view
```

The first wedge may explain an existing bundle by reading files and static code
text, but it must not execute code, mutate bundle files, control hardware,
install dependencies, assert source-of-record authority, or repair the bundle.

## Basis

This decision is promoted from:

- [`jc-001-work-bundle-explanation-journey.md`](jc-001-work-bundle-explanation-journey.md);
- [`jc-001-existing-bundle-to-explainable-context-wedge.md`](jc-001-existing-bundle-to-explainable-context-wedge.md);
- [`jc-001-concepts-and-contracts.md`](jc-001-concepts-and-contracts.md);
- [`jc-001-static-analysis-spike.md`](jc-001-static-analysis-spike.md).

The static-analysis spike validated that the synthetic fixture can produce an
evidence view preserving roles, relations, conflicts, missing facts, sharing
boundaries, and the no-execution/no-mutation boundary.

## Accepted Boundary

The first wedge can include:

- a bounded work-bundle inventory;
- artifact roles from the first-wedge vocabulary;
- selected-context candidates without authority claims;
- generated-sidecar and copied-snapshot relations;
- static code references read as text only;
- setup evidence treated as declared or observed evidence, not physical truth;
- variant and backup ambiguity;
- visible conflicts;
- explicit producer fact gaps;
- sharing-boundary labels. The current prototype validates public-safe fixture
  labels; internal-safe view differences remain follow-on validation.

The evidence view should preserve ambiguity. It may say that an artifact
appears selected, copied, generated, conflicting, redacted, or missing a
producer fact. It must not silently choose a winner or convert inferred
evidence into truth.

## Deferred Boundary

The first wedge does not include:

- managed execution;
- hardware or driver integration;
- environment solving or dependency installation;
- write-back, repair, rollback, or calibration mutation;
- automatic notebook execution;
- opaque binary inspection beyond safe categorization;
- known-good comparison;
- scientific equivalence scoring;
- support-boundary export policy;
- durable storage schema;
- general parser framework;
- subsystem ownership decisions beyond this wedge.

These may become later scope after a separate evidence-backed decision. Use a
journey, wedge, spike, ADR, prototype result, or ownership map as appropriate.

## Producer Facts Identified For Future Write Decisions

Read-side explanation showed that later write decisions should decide how to
preserve these facts when bundles are produced:

- preferred bundle anchor;
- selected settings path;
- selection reason;
- producer timestamp or freshness marker;
- generated sidecar source;
- generated sidecar invalidation rule;
- copied snapshot source and coverage;
- code origin or immutable code reference;
- sharing-boundary policy for sensitive source details.

The accepted passive wedge owns their missing-fact vocabulary and reporting.
It does not accept write-side product scope or make these facts prerequisites
for passive explanation.

## Consequences

The first read-only prototype and second public-safe fixture validate this
boundary at fixture scale. The next product or architecture choice is whether
to seed a small capability map from the provisional ownership pass or select a
second journey to test those owners under different pressure.

Confidence remains narrative-based, not numeric. Code-reference handling stays
static until a later Code Asset Registry or Managed Code Runner decision
exists.

Capability names touched by this wedge remain provisional pressure labels
until a capability map promotes ownership boundaries.

## Reversal Criteria

Revisit this decision if one of these occurs:

- users cannot get value from passive explanation without immediate write-back
  or execution;
- real fixture analysis cannot preserve ambiguity without excessive manual
  curation;
- public-safe reporting loses too much diagnostic value to support the journey;
- the first prototype requires a general parser or storage model before the
  evidence view is useful.

## Prototype Scope

[`jc-001-passive-evidence-view-prototype-scope.md`](jc-001-passive-evidence-view-prototype-scope.md)
defines the first implementation-facing prototype scope for this decision. Keep
the prototype read-only and fixture-sized unless a later scope document
explicitly promotes a broader parser, storage, UI, or capability-ownership
decision.
