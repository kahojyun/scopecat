# JC-001 Concepts And Contracts

## Status

Ready; validated by the first static-analysis spike and promoted by accepted
decision.

## Purpose

Identify the minimum domain concepts and cross-pressure contracts needed for
[`jc-001-existing-bundle-to-explainable-context-wedge.md`](jc-001-existing-bundle-to-explainable-context-wedge.md).

This note is scoped to the first wedge only. It is not a full domain model,
storage schema, API design, capability map, subsystem spec, or ADR.

## Contract Boundary

The first wedge needs contracts for static explanation:

```text
work bundle
  -> artifact inventory
  -> evidence relations
  -> conflict and missing-fact report
  -> sharing-safe evidence view
```

It does not need contracts for execution, hardware control, package
installation, settings mutation, rollback, database ownership, or live setup
truth.

## Minimum Concepts

| Concept | Definition | Required minimum |
| --- | --- | --- |
| Work bundle | A bounded set of files and references being explained together. | Stable bundle ID, source boundary, sharing boundary, and included artifact list. |
| Artifact | A file, reference, or synthetic fixture item that may carry evidence. | Artifact ID, display label, source location or redacted source category, role, evidence handling, and sharing boundary. |
| Anchor artifact | The artifact used as the entry point for explanation. | Exactly one preferred anchor or an explicit unresolved-anchor state. |
| Artifact role | The reason an artifact matters in the journey. | Controlled vocabulary for first wedge: anchor, selected context, generated sidecar, copied snapshot, variant, code reference, setup evidence, readiness hint, unknown, fixture-authored. `Generated sidecar` is fixture evidence wording for legacy colocated artifacts; later product docs should prefer companion artifact unless a source convention specifically uses sidecar. Backup is represented as relation-level ambiguity in this wedge. |
| Evidence handling | How strongly and safely the system can treat an artifact or relation. | Observed, inferred, generated, copied, user-declared, unchecked, unsafe-to-inspect, missing. |
| Evidence relation | A typed relationship between artifacts or facts. | Relation type, source artifact, target artifact, evidence handling, confidence narrative, and missing/unchecked flags. |
| Selected context | A context artifact that appears selected for the bundle. | Relation to anchor, selection evidence, conflicts, and explicit non-authoritative status. |
| Generated sidecar | An artifact that appears derived from selected context or code-shaped flow. | Produced-by or inferred-produced-by relation and freshness/unchecked label. |
| Copied snapshot | A copied view of context attached to a run-like artifact or bundle. | Copied-from or snapshot-of relation, source if known, and mismatch note when current context differs. |
| Code reference | Non-executed evidence about path selection, entrypoint-like behavior, or derivation flow. | Reference target, observed/inferred role, execution boundary, and unsafe-to-run flag when relevant. |
| Missing fact gap | A missing or insufficient fact needed for better explanation. | Missing fact type, affected artifacts, user impact, and suggested next check. |
| Sharing boundary | The allowed disclosure level for an artifact, field, or report section. | First prototype: public-safe and redaction-sensitive public rendering. Follow-on policy: internal-safe, external-support-safe, and unsafe-to-share. |
| Evidence view | The user-facing report produced by the wedge. | Role inventory, relations, conflicts, missing facts, sharing summary, and next checks. |

## Artifact Role Vocabulary

The first wedge should use a small role vocabulary:

| Role | Meaning | Design pressure |
| --- | --- | --- |
| Anchor | Entry point for explanation. | Run and bundle evidence. |
| Selected context | Context that appears selected for the bundle. | Settings and context evidence. |
| Generated sidecar | Derived artifact associated with selected context or code-shaped flow. | Run/bundle evidence plus settings/context evidence. |
| Copied snapshot | Copied state attached to a run-like artifact or bundle. | Run/bundle evidence plus settings/context evidence. |
| Variant | Related branch that may represent a different setup, method, or time period. | Settings/context evidence; later comparability pressure. |
| Code reference | Static code-shaped evidence, not executed code. | Code and dependency provenance. |
| Setup evidence | Registry-like or physical/setup context treated as declared or observed evidence. | Setup and runtime boundary evidence. |
| Readiness hint | Static dependency or environment clue. | Execution readiness evidence. |
| Unknown | Included artifact with unclear role. | Cross-route triage. |
| Fixture-authored | Synthetic or test-only artifact. | Fixture/tooling only. |

Design pressure is provisional. It indicates why the role matters, not where
later ownership must land.

## Evidence Relation Vocabulary

The first wedge should support only these relation types:

| Relation | Meaning | Non-goal |
| --- | --- | --- |
| `anchors` | Artifact starts or bounds the explanation. | Does not imply source-of-record truth. |
| `appears-selected-for` | Context appears selected for the bundle. | Does not imply authoritative configuration. |
| `conflicts-with` | Related artifacts disagree in shape, value, role, or freshness. | Does not decide which one is correct. |
| `generated-from` | Sidecar appears derived from another artifact or code-shaped flow. | Does not prove current freshness. |
| `copied-from` | Artifact appears copied or snapshotted from another context. | Does not provide transaction semantics. |
| `references-code` | Artifact or bundle has non-executed code-shaped evidence. | Does not accept execution or code identity ownership. |
| `has-variant` | Bundle has a related branch or variant. | Does not infer active precedence. |
| `has-backup` | Bundle has a related backup. | Does not infer rollback target. |
| `missing-fact` | Useful source information is absent or unknown and would improve later explanation. | Does not fabricate inferred truth or make passive explanation depend on producer support. |
| `redacts` | Public/support view hides or categorizes sensitive evidence. | Does not erase internal diagnostic value. |

## Cross-Pressure Contracts

### Bundle Inventory Contract

Purpose: run and bundle evidence provides a bounded artifact inventory for the
wedge.

Minimum fields:

- bundle ID;
- source boundary;
- artifact ID;
- artifact label;
- artifact role;
- evidence handling;
- sharing boundary;
- included/excluded reason.

Rules:

- every report starts from one bundle boundary;
- every included artifact must have a role or `unknown`;
- excluded artifacts can be summarized by category when useful;
- inventory does not imply execution, import, mutation, or source-of-record
  ownership.

### Context Evidence Contract

Purpose: settings and context evidence explains selected settings, snapshots,
generated context, variants, and conflicts as evidence.

Minimum fields:

- context artifact ID;
- context role;
- selection evidence;
- freshness or unchecked label;
- conflict list;
- non-authoritative marker.

Rules:

- selected context is never silently promoted to truth;
- conflicts stay visible;
- copied snapshots and generated sidecars retain their own relation labels;
- write-back, rollback, and calibration mutation are out of scope.

### Code Reference Contract

Purpose: code and dependency provenance contributes static code-shaped evidence
without managed execution.

Minimum fields:

- code reference ID;
- referenced artifact;
- observed or inferred behavior;
- related context artifact;
- execution boundary;
- unsafe-to-run flag when relevant.

Rules:

- code references may explain path selection or derivation flow;
- the wedge must not execute, import, test, install, or rewrite code;
- code reference identity can remain lightweight until a later runner or code
  asset decision exists.

### Setup Evidence Contract

Purpose: setup and runtime boundary evidence contributes setup or registry-like
evidence without device control.

Minimum fields:

- setup evidence artifact;
- declared or observed status;
- related context or code reference;
- sharing boundary;
- unsafe-to-verify flag when relevant.

Rules:

- setup evidence is not software-proof of physical truth;
- no live device query, lease, apply, driver mutation, or service startup is
  accepted;
- setup evidence can support explanation, conflict display, and redaction.

### Readiness Hint Contract

Purpose: execution readiness pressure is represented only as static readiness
evidence.

Minimum fields:

- readiness hint ID;
- source artifact;
- dependency or environment category;
- evidence handling;
- suggested next check.

Rules:

- readiness hints do not require execution supervision;
- no package installation, environment solving, worker fleet, or shell-command
  product surface is accepted;
- readiness can be omitted when no static clue is visible.

### Conflict Display Contract

Purpose: Comparability pressure contributes within-bundle conflict display
without known-good comparison.

Minimum fields:

- conflict ID;
- artifact pair or relation;
- conflict type;
- affected missing fact;
- user-visible implication;
- next check.

Rules:

- conflict display does not score scientific equivalence;
- conflict display does not pick a winner unless evidence explicitly says so;
- known-good references remain follow-on scope.

### Sharing Boundary Contract

Purpose: the first prototype preserves public-safe fixture labels and the
existence of redacted evidence. Markdown and JSON redaction for non-public
artifact labels, bundle metadata, redaction-policy metadata, and source-derived
status text has regression coverage. The detailed fixture manifest and
public-output identity rules are documented in
[`jc-001-manifest-and-public-output-contract.md`](jc-001-manifest-and-public-output-contract.md);
internal-safe diagnostics and support-boundary export policy remain follow-on
scope.

Minimum fields:

- artifact or field family;
- sharing boundary;
- redaction behavior;
- fixture-authored public handle or fixture-authored redaction handle.

Rules:

- public-safe output can preserve the existence and role of redacted evidence;
- redaction must not turn unknown or unsafe evidence into absent evidence;
- bundle and artifact IDs used in public output must be public-safe fixture
  slugs, fixture-authored public handles, or fixture-authored redaction
  handles, not source-derived hashes, unsafe source labels, or manifest-order
  labels;
- internal diagnostic retention remains follow-on prototype scope;
- support-boundary export is a separate policy decision, not assumed public.

## Evidence View Contract

The wedge output should be a static evidence report with these sections:

1. Bundle summary.
2. Artifact-role inventory.
3. Selected-context explanation.
4. Generated and copied relation summary.
5. Code-reference summary.
6. Static readiness hint summary.
7. Variant, backup, and unknown artifact summary.
8. Conflict and missing-fact report.
9. Sharing-boundary summary.
10. Next checks.

The report must not contain:

- execution results from running source code;
- hardware state claims;
- automatic repair instructions;
- source-of-record assertions;
- numeric trust scores;
- public leakage of redaction-sensitive evidence.

## Spike Result

The first technical spike stayed inside this question:

```text
Can a static analyzer produce the JC-001 evidence view from the synthetic
fixture, preserving roles, relations, conflicts, missing facts, and sharing
boundaries without execution or mutation?
```

[`jc-001-static-analysis-spike.md`](jc-001-static-analysis-spike.md) validates
that a narrow static analyzer can produce the evidence view from the synthetic
fixture while preserving roles, relations, conflicts, missing facts, sharing
boundaries, and the no-execution/no-mutation boundary. The validated boundary
is promoted by
[`jc-001-passive-evidence-view-decision.md`](jc-001-passive-evidence-view-decision.md).

The accepted decision owns the deferred boundary beyond the static evidence
view.

## Open Questions

- Should `selected context`, `generated sidecar`, and `copied snapshot` be one
  relation family with subtypes?
- Which artifact roles should be user-facing wording versus internal labels?
- Is `evidence handling` the same concept as confidence, or should confidence
  remain purely narrative for this wedge?
- How much source location detail can internal-safe output retain before a
  separate support/export policy is needed?
- Can code references remain file-level, or does the first spike need
  function/cell-level references?
- Which contract should own missing-fact wording: bundle inventory, context
  evidence, or evidence view?

## Current Downstream

These concepts are used by the accepted passive evidence-view decision,
two-fixture prototype scope, and provisional ownership pass. Broader scope
requires a later evidence-backed decision.
