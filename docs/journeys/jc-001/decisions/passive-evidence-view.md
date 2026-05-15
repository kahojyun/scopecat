# JC-001 Passive Evidence View Decision

## Status

Accepted boundary on 2026-05-12.

This decision is fixture validated and boundary accepted. It is not user
validated, product accepted, or a durable subsystem-ownership decision.

## Decision

Scopecat accepts the first `JC-001` product slice as a passive evidence-view
boundary:

```text
existing work bundle
  -> static artifact-role inventory
  -> evidence relations
  -> conflict and missing-fact report
  -> sharing-safe evidence view
```

The first slice may explain an existing bundle by reading files and static code
text, but it must not execute code, mutate bundle files, control hardware,
install dependencies, assert source-of-record authority, or repair the bundle.

## Basis

This decision is promoted from:

- [`../journey.md`](../journey.md);
- [`../slices/passive-evidence-view.md`](../slices/passive-evidence-view.md);
- [`../contracts/evidence-view.md`](../contracts/evidence-view.md);
- [`../prototypes/static-analysis-spike.md`](../prototypes/static-analysis-spike.md).

The static-analysis spike validated that the synthetic fixture can produce an
evidence view preserving roles, relations, conflicts, missing facts, sharing
boundaries, and the no-execution/no-mutation boundary.

## Accepted Boundary

The first slice can include:

- a bounded work-bundle inventory;
- artifact roles from the first slice vocabulary;
- selected-context candidates without authority claims;
- generated-sidecar and copied-snapshot relations;
- static code references read as text only;
- setup evidence treated as declared or observed evidence, not physical truth;
- variant evidence and backup relation ambiguity;
- visible conflicts;
- explicit missing-fact gaps;
- sharing-boundary labels. The current prototype validates public-safe fixture
  output and redaction-sensitive public rendering for non-public labels and
  metadata; internal-safe, external-support-safe, and unsafe-to-share view
  policies remain follow-on validation. The current manifest and public-output
  identity rules are documented in
  [`../contracts/manifest-and-public-output.md`](../contracts/manifest-and-public-output.md).

The evidence view should preserve ambiguity. It may say that an artifact
appears selected, copied, generated, conflicting, redacted, or missing a useful
fact. It must not silently choose a winner or convert inferred
evidence into truth.

## Deferred Boundary

The first slice does not include:

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
- subsystem ownership decisions beyond this slice.

These may become later scope after a separate evidence-backed decision. Use a
journey, slice, spike, ADR, prototype result, or ownership map as appropriate.

## Missing-Fact Vocabulary Kept In Read Scope

Read-side explanation showed that the report should keep these absent or
ambiguous facts visible when they affect user interpretation:

- preferred bundle anchor;
- selected settings path;
- selection reason;
- source timestamp or freshness marker;
- generated sidecar source;
- generated sidecar invalidation rule;
- copied snapshot source and coverage;
- code origin or immutable code reference;
- sharing-boundary policy for sensitive source details.

The accepted passive slice owns only their missing-fact vocabulary and
reporting. It does not accept write-side product scope or make these facts
prerequisites for passive explanation.

## Consequences

The first read-only prototype and second public-safe fixture validate this
boundary at fixture scale. They do not yet show that representative users can
complete the task better, interpret every confidence signal correctly, or treat
the passive evidence view as accepted product direction.

Follow-on status: the second-journey path is now represented by `JC-002`, which
tests selected-run analysis handoff pressure against the provisional `JC-001`
design-pressure owners. Any future `JC-001` reopen or extension should update
this decision or its owning scope, contract, or ownership document before
changing cross-journey tracker coordination.

Confidence remains narrative-based, not numeric. Code-reference handling stays
static until a later code-provenance or execution-readiness decision exists.

Design-pressure labels touched by this slice remain provisional until a later
capability map promotes ownership boundaries.

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

[`../prototypes/passive-evidence-view.md`](../prototypes/passive-evidence-view.md)
defines the first implementation-facing prototype scope for this decision. Keep
the prototype read-only and fixture-sized unless a later scope document
explicitly promotes a broader parser, storage, UI, or capability-ownership
decision.
