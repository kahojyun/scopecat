# JC-001 Existing Bundle To Explainable Context Wedge

## Status

Promoted through concepts, decision, prototype, and ownership pass.

## Purpose

Shape the first W4 migration wedge from
[`jc-001-capability-adoption-extraction.md`](jc-001-capability-adoption-extraction.md).

This wedge is the first thin vertical slice:

```text
existing work bundle
  -> explainable context bundle
```

It is scoped to offline explanation of one existing bundle. It does not define
implementation architecture, storage contracts, subsystem specs, or technical
spikes.

## User-Visible Outcome

A user opens an existing work bundle and sees a public-safe or internal-safe
evidence view that explains:

- anchor artifacts;
- selected-context candidates;
- generated sidecars;
- copied run-bound snapshots;
- variants and backups;
- code-shaped provenance;
- producer-fact gaps;
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
- variant and backup ambiguity;
- producer-side missing-fact report;
- public-safe/internal-safe sharing boundary labels.

Excluded:

- managed execution;
- notebook execution or notebook-state capture;
- hardware control, driver communication, setup mutation, or service startup;
- settings write-back, calibration mutation, rollback, or restore;
- package installation, environment solving, background agents, cloud login, or
  mandatory network services;
- old-history import, Data Vault emulation, or general file organization;
- known-good comparison, scientific-equivalence scoring, or cross-system
  transfer claims;
- full ELN, report generator, support-ticketing product, or collaboration
  workflow.

## Capabilities Involved

| Capability pressure | Role in this wedge |
| --- | --- |
| Measurement History | Provides the bundle or run-like anchor and artifact-role inventory. |
| Parameter Memory | Explains selected settings, snapshots, generated context, variants, conflicts, freshness, and unknown active state as evidence. |
| Code Asset Registry | Records or infers non-executed code references that explain settings selection and derivation. |
| Instrument Runtime | Treats setup or registry-like files as declared or observed evidence only. |
| Managed Code Runner | Contributes static readiness and dependency clues only. |
| Comparability and known-good diff | Provides within-bundle conflict display, not known-good comparison. |

## Producer Facts Preserved

The wedge should expose whether these facts are observed, inferred, copied,
generated, user-declared, unchecked, unsafe to inspect, or missing:

| Producer fact | Wedge handling |
| --- | --- |
| Bundle or run-like anchor | Required as the entry point for the evidence view. |
| Artifact role | Required for every included artifact. |
| Selected settings source | Required when settings-like files are present. |
| Snapshot relation | Required when copied settings or run-bound snapshots are present. |
| Generated relation | Required when sidecars appear derived from selected context. |
| Code reference | Required when code-shaped evidence explains selection or derivation. |
| Variant lineage | Optional, but at least one variant/backup ambiguity case should be representable. |
| Dependency/readiness hint | Optional; include only when visible without execution. |
| Sharing boundary | Required for each artifact or field family. |

## Evidence View Requirements

The wedge output should include:

- artifact table grouped by role;
- relation list for selected context, generated sidecars, copied snapshots, and
  variants;
- conflict notes between related artifacts;
- evidence-handling labels;
- missing producer-fact report;
- sharing-boundary/redaction summary;
- next-check recommendations.

The output should avoid a single overall trust score. It should preserve the
specific reasons a bundle is explainable, ambiguous, stale, incomplete, or
unsafe to share.

## Validation Checks

| Check | Pass condition |
| --- | --- |
| Role inventory | The wedge identifies anchor, selected context, generated sidecar, copied snapshot, variant, backup, unknown, and code-shape evidence where present. |
| Context ambiguity | Related config/settings artifacts can be shown as related but conflicting without declaring one authoritative truth. |
| Producer gaps | Missing selected-source, generated-relation, copied-relation, or code-reference facts remain visible. |
| No execution | The wedge produces useful output without running code, notebooks, drivers, services, or hardware routines. |
| No mutation | The wedge does not write back, repair, restore, normalize, or reorder source artifacts. |
| Sharing boundary | Internal-safe and public-safe views can differ without losing the role of redacted evidence. |
| Low ceremony | The wedge works on ordinary files and lightweight manifests, not only on Scopecat-native projects. |
| Future write pressure | The wedge identifies which facts future producers should record without requiring a managed runner or database now. |

## Minimum Domain Concepts Before Spike

These concepts are candidates for W6 contract extraction. They are not yet
accepted architecture:

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
| Sharing boundary | Whether evidence is internal-safe, public-safe, external-support-safe, or redaction-sensitive. |

## Spike Candidate

Do not run a technical spike until the concept boundary is reviewed. If a spike
is approved later, the narrow question should be:

```text
Can a static analyzer produce the JC-001 evidence view from the synthetic
fixture, preserving roles, relations, conflicts, missing facts, and sharing
boundaries without execution or mutation?
```

Expected spike output would be a static evidence report, not a product UI,
database schema, execution runner, or parser for arbitrary legacy files.

## Open Questions

- Should `selected context`, `generated sidecar`, and `copied snapshot` share
  one relation model, or stay separate for the first wedge?
- Which artifact roles are user-facing terms, and which are internal analysis
  labels?
- What is the smallest freshness model that avoids implying live truth?
- Can code references stay as plain evidence, or do they need code-asset
  identity earlier than expected?
- How should public-safe exports preserve the existence of redacted evidence
  without leaking sensitive details?
- Which static readiness hints are valuable enough to include in the first
  spike?

## Promoted To

This wedge is promoted to
[`jc-001-concepts-and-contracts.md`](jc-001-concepts-and-contracts.md),
validated by [`jc-001-static-analysis-spike.md`](jc-001-static-analysis-spike.md),
and accepted by
[`jc-001-passive-evidence-view-decision.md`](jc-001-passive-evidence-view-decision.md).
