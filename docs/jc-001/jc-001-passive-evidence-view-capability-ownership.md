# JC-001 Passive Evidence View Capability Ownership

## Status

Drafting; scoped to the accepted passive evidence-view wedge.

## Purpose

Assign provisional capability ownership for the facts and contracts used by the
accepted `JC-001` passive evidence view.

This note is scoped to
[`jc-001-passive-evidence-view-decision.md`](jc-001-passive-evidence-view-decision.md)
and the two-fixture prototype recorded in
[`jc-001-passive-evidence-view-prototype-scope.md`](jc-001-passive-evidence-view-prototype-scope.md).
It is not a full capability map, subsystem spec, storage design, package
layout, parser framework, UI design, execution plan, or hardware integration
plan.

## Ownership Rule

Assign ownership by durable fact family, not by implementation file or current
prototype function.

```text
evidence-view fact
  -> owning capability pressure
  -> allowed first-wedge responsibility
  -> explicit non-ownership
```

The first owner is responsible for vocabulary, validation expectations, and
future producer obligations for that fact family. It does not automatically
own storage, UI, services, execution, hardware, or write-back behavior.

## Provisional Owners

| Fact or contract family | Provisional owner | First-wedge responsibility | Non-ownership |
| --- | --- | --- | --- |
| Work bundle boundary | Measurement History | Own bundle ID, source boundary, included artifact list, excluded categories when needed, and the unresolved or preferred anchor state. | Does not own old-history import, durable database schema, acquisition, resumability, or live run records yet. |
| Artifact-role inventory | Measurement History | Own the requirement that every included artifact has a role or `unknown`, evidence handling, sharing boundary, and included reason. | Does not decide selected settings authority, setup truth, code identity, or conflict winner. |
| Selected context | Parameter Memory | Own selected-looking settings/context evidence, non-authoritative status, freshness labels, and selected-source missing facts. | Does not own write-back, rollback, calibration mutation, universal parameter schema, or source-of-record authority. |
| Generated sidecar relation | Measurement History plus Parameter Memory | Measurement History owns bundle attachment and artifact-inventory presence; Parameter Memory owns generated-from relation semantics, freshness gaps, and invalidation-rule producer obligations when sidecars exist. | Does not prove sidecar freshness or execute generators. |
| Copied snapshot relation | Measurement History plus Parameter Memory | Measurement History owns run/bundle attachment; Parameter Memory owns copied-from relation, coverage gaps, and context mismatch implications. | Does not provide transaction semantics, restore, rollback, or completeness guarantees. |
| Variant and backup ambiguity | Parameter Memory | Own variant/backup visibility and non-precedence labels for settings/context branches. | Does not choose active variant, rollback target, or known-good reference. |
| Static code reference | Code Asset Registry | Own text-only code references, observed static clues, unsafe-to-run boundary, and code identity missing facts. | Does not own execution, package management, notebook state, code registry service, or immutable code identity yet. |
| Setup evidence | Instrument Runtime | Own setup/registry-like evidence as declared or observed context with sharing boundary and unsafe-to-verify labels. | Does not own live device truth, leases, driver mutation, service startup, or hardware control. |
| Static readiness hint | Managed Code Runner | Own static readiness clues and readiness-gap wording when visible without execution. | Does not own execution supervision, package installation, environment solving, shell-command UX, workers, or logs. |
| Conflict display | Comparability and known-good diff | Own within-bundle conflict records, affected producer fact, user-visible implication, and next-check wording. | Does not own known-good authority, scientific equivalence scoring, normalization, or cross-system transfer claims. |
| Sharing boundary | Evidence view boundary, with input from each owner | Own report-level preservation of roles and relations for public-safe fixture labels. Each fact owner provides the boundary label for its artifacts or fields. | Does not define internal-safe view differences, external support export workflow, legal policy, or public documentation examples. |
| Missing producer facts | Evidence view boundary, with one fact owner per gap | Own first-class display of missing facts and routing to the owner of the missing fact family. | Does not fabricate inferred truth or require write-side implementation before passive explanation. |

## Dependency Direction

The passive evidence view depends on capability facts in this order:

1. Measurement History bounds the work bundle and inventory.
2. Parameter Memory, Code Asset Registry, Instrument Runtime, and Managed Code
   Runner contribute typed evidence families.
3. Comparability and known-good diff contributes conflict display for
   within-bundle disagreements.
4. The evidence view composes these facts into a report without claiming
   source-of-record truth.

No lower row can force a broader adoption step in an upper row. For example,
static readiness hints do not require a Managed Code Runner product surface,
and setup evidence does not require Instrument Runtime hardware control.

## Prototype Evidence

The two public-safe fixtures provide ownership pressure:

| Fixture | Ownership pressure validated |
| --- | --- |
| `tests/fixtures/jc001-layered-config-bundle/` | Multiple anchors, selected context, setup evidence, generated sidecars, copied snapshot, variant/backup ambiguity, code references, conflicts, missing producer facts, and public-safe sharing boundary. |
| `tests/fixtures/jc001-minimal-unknown/` | Single anchor, selected context, unknown artifact preservation, explicit absence of generated/copied/variant artifacts, static readiness hint, zero-conflict output, and conditional missing facts. |

The fixtures validate owner boundaries at the evidence-view level only. They do
not validate storage ownership, UI ownership, parser generalization, or runtime
ownership.

## Provisional For This Wedge

The first wedge may rely on these provisional ownership decisions while avoiding
broader subsystem promotion:

- Measurement History owns the bundle and artifact inventory shape.
- Parameter Memory owns selected-context, generated-sidecar, copied-context,
  and variant/backup evidence semantics.
- Code Asset Registry owns static code-reference evidence semantics.
- Instrument Runtime owns setup evidence semantics without live verification.
- Managed Code Runner owns static readiness hint semantics without execution.
- Comparability and known-good diff owns within-bundle conflict display only.
- The evidence view owns composition, missing-fact display, and sharing-boundary
  preservation across report views.

## Deferred

Do not promote these from this ownership pass:

- package layout;
- CLI contract;
- parser framework;
- database schema;
- product UI;
- public sample-data policy;
- support-export workflow;
- managed execution;
- hardware integration;
- source-of-record authority;
- full capability map;
- subsystem specs.

## Open Questions

- Should `copied snapshot` remain shared between Measurement History and
  Parameter Memory, or should one capability own the relation and the other own
  only its display context?
- Should sharing boundary become its own cross-cutting policy owner after
  external support workflows appear?
- When does Code Asset Registry need immutable code identity instead of
  text-only code references?
- Which second journey should test whether these provisional owners hold beyond
  passive bundle explanation?

## Next Step

Use this ownership pass to choose the next product/architecture move:

- draft a small capability map seeded only by accepted `JC-001` ownership; or
- select a second journey to test whether these owners hold under different
  evidence pressure before writing a broader capability map.
