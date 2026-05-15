# JC-001 Existing Bundle To Explainable Context Slice

## Status

Ready as the `JC-001` accepted slice; validated by concepts, decision, prototype, and
ownership pass.

## Purpose

Shape the first validation slice from
[`../design-pressure.md`](../design-pressure.md).

This slice is the first thin vertical slice:

```text
existing work bundle
  -> explainable context bundle
```

It is scoped to offline explanation of one existing bundle. It does not define
implementation architecture, storage contracts, subsystem specs, or technical
spikes.

## User-Visible Outcome

A user opens an existing work bundle and sees a boundary-aware evidence view that
explains:

- anchor artifacts;
- selected-context candidates;
- generated sidecars;
- copied run-bound snapshots;
- variants and backups;
- code-shaped provenance;
- missing-fact gaps;
- conflicts, missing evidence, and unchecked relations;
- sharing boundaries.

The user can decide what must be checked before analysis, handoff, or reuse
without running code, touching hardware, mutating settings, or trusting a new
source of truth.

## Primary User Story

As an experiment user inheriting or reopening a work bundle, I want Scopecat to
explain which files and references appear to define the context of the bundle,
which ones conflict or are unchecked, and which facts are safe to share, so I
can continue work without copying everything blindly or treating stale evidence
as truth.

## Scope

Included:

- one existing bundle or synthetic fixture at a time;
- static artifact inventory;
- artifact role classification;
- selected-context explanation;
- generated-sidecar and copied-snapshot relations;
- code-shape provenance without execution;
- variant evidence and backup relation ambiguity;
- missing-fact report;
- public-safe fixture sharing-boundary labels.

The accepted decision owns the deferred boundary for this slice.

## Design Pressures Involved

| Design pressure | Role in this slice |
| --- | --- |
| Run and bundle evidence | Provides the bundle or run-like anchor and artifact-role inventory. |
| Settings and context evidence | Explains selected settings, snapshots, generated context, variants, conflicts, freshness, and unknown active state as evidence. |
| Code and dependency provenance | Surfaces non-executed code-shaped evidence that explains settings selection and derivation. |
| Setup and runtime boundary evidence | Treats setup or registry-like files as declared or observed evidence only. |
| Execution readiness evidence | Contributes static readiness and dependency clues only. |
| Conflict diagnostics | Provides within-bundle conflict display, not known-good comparison. |

## Missing Facts Preserved

The slice should expose whether these facts are observed, inferred, copied,
generated, user-declared, unchecked, unsafe to inspect, or missing. They are
read-side report facts, not required producer inputs.

| Missing-fact family | Slice handling |
| --- | --- |
| Bundle or run-like anchor | Represent as the entry point for the evidence view. |
| Artifact role | Represent for every included artifact. |
| Selected settings source | Represent as observed, inferred, or missing when settings-like files are present. |
| Snapshot relation | Represent as observed, inferred, or missing when copied settings or run-bound snapshots are present. |
| Generated relation | Represent as observed, inferred, or missing when sidecars appear derived from selected context. |
| Code reference | Represent as lightweight evidence when code-shaped clues explain selection or derivation. |
| Variant lineage | Optional, but at least one variant/backup ambiguity case should be representable. |
| Dependency/readiness hint | Optional; include only when visible without execution. |
| Sharing boundary | Represent for each artifact or field family. |

## Evidence View Requirements

The slice output should include:

- artifact table grouped by role;
- relation list for selected context, generated sidecars, copied snapshots, and
  variants;
- conflict notes between related artifacts;
- evidence-handling labels;
- missing-fact report;
- sharing-boundary/redaction summary;
- next-check recommendations.

The output should avoid a single overall trust score. It should preserve the
specific reasons a bundle is explainable, ambiguous, stale, incomplete, or
unsafe to share.

## Validation Checks

| Check | Pass condition |
| --- | --- |
| Role inventory | The slice identifies anchor, selected context, generated sidecar, copied snapshot, variant, unknown, and code-shape evidence where present; backup ambiguity is represented through relations and non-precedence labels. |
| Context ambiguity | Related config/settings artifacts can be shown as related but conflicting without declaring one authoritative truth. |
| Missing-fact gaps | Missing selected-source, generated-relation, copied-relation, or code-reference facts remain visible. |
| No execution | The slice produces useful output without running code, notebooks, drivers, services, or hardware routines. |
| No mutation | The slice does not write back, repair, restore, normalize, or reorder source artifacts. |
| Sharing boundary | Public-safe fixture output preserves the role of redacted evidence; internal-safe view differences remain follow-on validation. |
| Low ceremony | The slice works on ordinary files and lightweight manifests, not only on Scopecat-native projects. |
| Future support stays optional | The slice identifies useful missing facts without requiring a managed runner, database, or write-side API now. |

## Concept And Spike Handoff

This slice was promoted into
[`../contracts/evidence-view.md`](../contracts/evidence-view.md) and validated
by [`../prototypes/static-analysis-spike.md`](../prototypes/static-analysis-spike.md).
The concept set used for that handoff was:

| Concept | Why it is needed |
| --- | --- |
| Work bundle | The bounded object being explained. |
| Anchor artifact | The starting point for explanation. |
| Artifact role | The user-facing reason an artifact matters. |
| Evidence handling | Whether evidence is observed, inferred, generated, copied, unchecked, user-declared, unsafe, or missing. |
| Selected context | A context artifact that appears selected for the bundle, without being authoritative truth. |
| Generated sidecar | An artifact derived from selected context or code-shaped flow. |
| Copied snapshot | A copied view of context attached to a run-like artifact. |
| Code reference | Non-executed evidence about path selection or derivation flow. |
| Sharing boundary | Whether evidence is public-safe or redaction-sensitive in the current accepted fixture boundary. Internal-safe and external-support-safe remain follow-on sharing-policy decisions. |

## Open Questions

- Which second journey should test the first slice concept and ownership
  pressure?
- Which concept names should become durable user-facing terms rather than
  internal evidence labels?
- When does code reference handling need immutable identity rather than
  text-only evidence?
