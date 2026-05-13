# JC-001 Passive Evidence View Capability Ownership

## Status

Provisional; scoped to the accepted passive evidence-view wedge.

## Purpose

Identify provisional owner pressure for the facts and contracts used by the
accepted `JC-001` passive evidence view.

This note is scoped to
[`jc-001-passive-evidence-view-decision.md`](jc-001-passive-evidence-view-decision.md)
and the two-fixture prototype recorded in
[`jc-001-passive-evidence-view-prototype-scope.md`](jc-001-passive-evidence-view-prototype-scope.md).
It is not a full capability map, subsystem spec, storage design, package
layout, parser framework, UI design, execution plan, or hardware integration
plan.

## Ownership Rule

Assign provisional owner pressure by durable fact family, not by implementation
file or current prototype function.

```text
evidence-view fact
  -> owning capability pressure
  -> allowed first-wedge responsibility
  -> explicit non-ownership
```

The provisional owner pressure identifies which capability currently carries
passive-view vocabulary pressure, validation expectations, and missing-fact
wording pressure for that fact family. This is not durable subsystem ownership.
Future producer behavior still needs a separate evidence-backed decision.

## Provisional Owner Pressure

| Fact or contract family | Provisional owner pressure | Accepted first-wedge responsibility | Non-ownership |
| --- | --- | --- | --- |
| Work bundle boundary | Measurement History | Defines bundle ID, source boundary, included artifact list, excluded categories when needed, and unresolved or preferred anchor state. | Does not own old-history import, durable database schema, acquisition, resumability, or live run records yet. |
| Artifact-role inventory | Measurement History | Requires every included artifact to have a role or `unknown`, evidence handling, sharing boundary, and included reason. | Does not decide selected settings provenance, setup truth, code identity, or conflict winner. |
| Selected context | Parameter Memory | Defines selected-looking settings/context evidence, non-authoritative status, freshness labels, and selected-source missing facts. | Does not own write-back, rollback, calibration mutation, universal parameter schema, or source-of-record authority. |
| Generated sidecar relation | Measurement History plus Parameter Memory | Measurement History defines bundle attachment and artifact-inventory presence; Parameter Memory defines generated-from relation semantics, freshness gaps, and invalidation-rule missing facts when sidecars exist. | Does not prove sidecar freshness or execute generators. |
| Copied snapshot relation | Measurement History plus Parameter Memory | Measurement History defines run/bundle attachment; Parameter Memory defines copied-from relation, coverage gaps, and context mismatch implications. | Does not provide transaction semantics, restore, rollback, or completeness guarantees. |
| Variant and backup ambiguity | Parameter Memory | Defines variant/backup visibility and non-precedence labels for settings/context branches. | Does not choose active variant, rollback target, or known-good reference. |
| Static code reference | Code Asset Registry | Defines text-only code references, observed static clues, unsafe-to-run boundary, and code identity missing facts. | Does not own execution, package management, notebook state, code registry service, or immutable code identity yet. |
| Setup evidence | Instrument Runtime | Defines setup/registry-like evidence as declared or observed context with sharing boundary and unsafe-to-verify labels. | Does not own live device truth, leases, driver mutation, service startup, or hardware control. |
| Static readiness hint | Managed Code Runner | Defines static readiness clues and readiness-gap wording when visible without execution. | Does not own execution supervision, package installation, environment solving, shell-command UX, workers, or logs. |
| Conflict display | Comparability and conflict review | Defines within-bundle conflict records, affected producer fact, user-visible implication, and next-check wording. | Does not own known-good authority, scientific equivalence scoring, normalization, or cross-system transfer claims. |
| Sharing boundary | Evidence view boundary, with input from each provisional pressure owner and fixture/tooling authors; current manifest/public-output rules documented in [`jc-001-manifest-and-public-output-contract.md`](jc-001-manifest-and-public-output-contract.md) | Preserves roles and relations in report output; validates fixture-authored public handles and fixture-authored redaction handles; redacts non-public artifact labels, bundle metadata, redaction-policy metadata, and source-derived status text. Each provisional pressure owner identifies boundary labels for its artifacts or fields. | Does not define internal-safe view differences, external support export workflow, legal policy, or public documentation examples. |
| Missing producer facts | Evidence view boundary, with one provisional pressure owner per gap | Displays missing facts as first-class output. Owner routing is a follow-on contract once producer-side facts are promoted. | Does not fabricate inferred truth, implement owner routing, or require write-side implementation before passive explanation. |

## Dependency Direction

The passive evidence view depends on capability facts in this order:

1. Measurement History bounds the work bundle and inventory.
2. Parameter Memory, Code Asset Registry, Instrument Runtime, and Managed Code
   Runner contribute typed evidence families.
3. Comparability and conflict review contributes conflict display for
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

The first wedge may rely on these provisional responsibility assignments while
avoiding broader subsystem promotion:

- Measurement History carries first-wedge pressure for bundle and artifact
  inventory wording.
- Parameter Memory carries first-wedge pressure for selected-context provenance,
  generated-sidecar, copied-context, and variant/backup evidence semantics.
- Code Asset Registry carries first-wedge pressure for static code-reference
  evidence semantics.
- Instrument Runtime carries first-wedge pressure for setup evidence semantics
  without live verification.
- Managed Code Runner carries first-wedge pressure for static readiness hint
  semantics without execution.
- Comparability and conflict review carries first-wedge pressure for
  within-bundle conflict display only.
- The evidence view carries first-wedge pressure for composition, missing-fact
  display, and sharing-boundary preservation across report views.

## Deferred

Generic deferred scope is owned by
[`jc-001-passive-evidence-view-decision.md`](jc-001-passive-evidence-view-decision.md).
This ownership pass adds only provisional fact-family owners for the accepted
evidence view.

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
