# Journey Candidate Operating Standard

## Status

Ready process standard for future `JC-###` work.

## Purpose

Define the smallest repeatable process for selecting, drafting, validating,
accepting, reopening, and retiring journey candidates without copying the full
`JC-001` document set by default.

This document owns process only. It is not a product vision, evidence
inventory, capability map, architecture decision, fixture manifest contract,
redaction policy, or subsystem spec.

Use [`../evidence/inventory.md`](../evidence/inventory.md) for `EV-###`,
`PN-###`, `TP-###`, and candidate `JC-###` source material. Use
[`../journeys/jc-001/README.md`](../journeys/jc-001/README.md) as an earned
example, not as a folder template.

## Core Rule

Start from evidence and a user journey. Add documents only when they remove
real ambiguity for the next decision or implementation.

```text
evidence
  -> journey
  -> validation slice
  -> decision or contract when needed
```

A new `JC` does not need separate selection, journey, contract, decision, and
prototype files at the start. Split only after length, reuse, review risk, or
implementation dependency makes the split useful.

## Status Language

Use statuses on specific documents, claims, fixtures, outputs, and decisions.
Avoid applying one broad status to a whole folder unless every artifact in that
folder is at the same level.

| Status | Use when | Does not mean |
| --- | --- | --- |
| Draft | Text exists, but evidence, scope, or acceptance is unstable. | Ready for implementation. |
| Ready | Coherent enough to guide the next analysis or design step. | Fixture, user, or product validation exists. |
| Fixture validated | Synthetic, redacted, or high-fidelity fixture checks pass. | Users can complete the task better. |
| User validated | Representative users complete the target task and interpret output correctly. | Broader product direction is accepted. |
| Accepted boundary | The project accepts a scoped product, domain, or architecture boundary until reopening criteria fire. | Product-market fit or broad subsystem acceptance. |
| Product accepted | Enough user and product evidence exists to treat the journey or route as product direction. | Future scope can skip decision gates. |
| Provisional | Evidence pressure is explicit but not accepted as a durable route, contract, or decision. | Accepted boundary. |
| Deferred | Scope is intentionally postponed and needs a later evidence-backed decision. | Rejected forever. |
| Reopened | Later evidence challenges a previous accepted claim or scope. | The whole earlier `JC` is invalid. |
| Superseded | A newer owner doc or decision replaces this artifact for future work. | The old artifact should be rewritten as if it never existed. |

Tracker and index labels are navigation metadata, not validation statuses.

## Minimum JC Record

Every promoted `JC` needs a public-safe committed floor. It can be one document
or several, but it must answer:

- why this candidate now;
- who the user is and what situation they are in;
- what source or fixture boundary defines validation;
- what evidence supports the pressure;
- what the future-state slice is;
- what is explicitly out of scope;
- what validation route or prototype will test it;
- what the next decision is.

If full-fidelity validation is non-public, the committed record must summarize
the public-safe source family, redaction reason, validation facts, and owner of
the private detail. Do not publish exact private paths, usernames, machine
names, instrument identifiers, lab labels, sample labels, or source-derived
location details.

## Document Splitting

Prefer one compact `README.md` or journey note until there is a reason to
split.

Common split points:

| Split | Create when |
| --- | --- |
| `selection.md` | The reason for selecting the journey has durable value after the main journey evolves. |
| `journey.md` | Current-state and future-state flow need room separate from prototype or decision details. |
| `snapshot-boundary.md`, `concept.md`, or similar | A draft product boundary needs reuse, but is not yet a stable contract. |
| `decisions/*.md` | Downstream work needs an accepted boundary with explicit reopening criteria. |
| `contracts/*.md` | Fixture, output, manifest, vocabulary, or public behavior depends on stable rules. |
| `prototypes/*.md` | Implementation or tests need a scoped validation target and known non-goals. |

Do not create capability maps, subsystem docs, owner routing, or broad
architecture scaffolds before a journey, prototype, or accepted decision needs
them.

## Decision Placement

Put durable decisions next to the smallest owner that can safely own them.

| Decision type | Owner |
| --- | --- |
| One journey's product boundary, deferred scope, and reopening criteria | `docs/journeys/<jc>/decisions/` |
| Stable fixture output, manifest vocabulary, relation semantics, or public behavior used by tests or downstream docs | `docs/journeys/<jc>/contracts/` |
| Draft boundary that still needs fixture or user validation | A compact journey-local note such as `snapshot-boundary.md`; do not call it a contract yet. |
| Cross-journey runtime, storage, apply, execution, integration, support, or ownership policy | Future `docs/architecture/` ADR, created only when more than one journey or implementation path depends on it. |
| Evidence wording, support level, source class, or candidate provenance | `docs/evidence/inventory.md` |

If a decision is hard to place, keep it as journey-local design pressure until
a second journey or implementation dependency proves that it needs a broader
owner.

Architecture ADR triggers should stay concrete. Create or reopen an ADR when a
journey or prototype needs to decide any of these boundaries:

- whether preview, dry-run, mock-run, and real apply share the same intent
  semantics;
- how desired state, requested state, observed state, and runtime-acknowledged
  actual state differ;
- which owner revalidates bounds, readiness, permissions, leases, environment,
  code identity, and live runtime capability before execution;
- which references must be frozen, hashable, or versioned before they can
  explain a run, handoff package, proposal, or runtime handoff;
- which component owns stop behavior, failure policy, audit records, and
  operator accountability for a bounded local run;
- whether a copied method, package, or plan is diagnostic evidence, a reusable
  template, or an execution-authoritative artifact.

## Change Routing

When a review or prototype result changes scope, update the owner of the changed
claim instead of copying the change through every index.

| Change | Update |
| --- | --- |
| Candidate wording, evidence rank, support level, or validation route | `docs/evidence/inventory.md`; tracker only if active coordination changes. |
| Journey situation, future-state outcome, non-goals, or next decision | Owning `docs/journeys/<jc>/README.md` or `journey.md`; tracker only for phase, link, or dependency changes. |
| Accepted boundary or reopening criteria | Owning `decisions/*.md`, plus dependent contracts, prototypes, fixtures, expected outputs, and tests. |
| Draft boundary used by a prototype | Journey-local boundary note and prototype doc; promote to contract only after downstream behavior needs stable rules. |
| Prototype behavior or validation output | Prototype doc, implementation, fixtures, expected outputs, and tests; contract only if stable public behavior changes. |
| Public output, identifiers, labels, relation targets, metadata, or redaction behavior | Public-output contract, fixtures, expected outputs, and tests; process standard only if the rule itself changes. |
| Cross-journey phase, priority, dependency, or route coordination | `docs/status/progress-tracker.md`. |
| Cross-journey runtime, apply, storage, or ownership policy | Future architecture ADR, plus all journey docs that depend on it. |

## Source And Sharing Gate

Before promoting a `JC`, identify the validation source. The source record can
be a committed public-safe fixture, a compact source section in the journey
note, or a private full-fidelity working map with a public summary.

For public docs and fixtures:

- use role-stable, fixture-authored, or opaque identifiers;
- redact local paths, usernames, machine names, instrument addresses, lab
  labels, sample labels, and source-derived project details;
- distinguish internal diagnostic detail from public or external sharing;
- record whether evidence is observed, declared, inferred, copied, generated,
  unchecked, unsafe-to-inspect, missing, or redacted.

Treat redaction as an owned workflow. Readers, analysis APIs, and consumer
mocks do not certify public safety unless they are explicitly the export or
redaction owner. Prefer whole-field path redaction or opaque IDs over retaining
path suffixes.

## Prototype Boundary Control

Prototype hardening should clarify the prototype's accepted responsibility, not
turn one fixture into a product framework.

Before a review-fix loop, state:

- what data, format, or behavior the prototype owns;
- what is fixture input produced by another workflow;
- what is only a consumer mock;
- what outputs are validation artifacts rather than product artifacts;
- what arbitrary user files the prototype does not parse, sanitize, secure,
  execute, or normalize.

When review finds a defect:

| Finding class | Default handling |
| --- | --- |
| Owned contract | Fix in the prototype and tests. |
| Fixture input | Fix the fixture or defer to the producing workflow. |
| Consumer mock | Keep only the smoke behavior needed for validation. |
| Caller behavior | Usually document as out of scope. |
| Arbitrary user artifact | Do not broaden parsing without a separate adapter or decision. |
| Security or sharing policy | Defer unless the prototype explicitly owns that policy. |

Stop hardening when remaining issues require new product surface, generic
parsing, redaction policy, permission design, execution management, storage, or
UI commitments that the current slice has not accepted.

## Acceptance Gates

### Journey Readiness

A journey is ready for fixture or prototype work when:

- the user situation and current workaround are concrete;
- the evidence basis and source class are stated;
- the selected slice has an entry condition, user-visible outcome, and exit
  condition;
- foundational pains, adoption guardrails, capability gaps, and baseline
  expectations are not mixed together;
- non-goals prevent accidental framework replacement, hardware authority,
  environment mutation, or broad platform adoption.

### Product Decision Readiness

A product decision is ready when a reviewer can answer:

- what decision is being made: build, validate, defer, reject, or reopen;
- what evidence supports it;
- what fixture, prototype, or user result validated it;
- what scope is accepted;
- what scope is deferred;
- what would reopen the decision;
- which document or implementation depends on the result.

### Contract Readiness

A contract is ready only when downstream behavior depends on stable rules. It
must state:

- owner document;
- allowed source and target roles;
- evidence and authority semantics;
- absence and missing-fact behavior;
- sharing behavior;
- fixture and expected-output coverage;
- reopening criteria.

## Reopening And Conflict Handling

Later `JC` work may extend, specialize, split, or replace earlier work. It
should not quietly generalize earlier scope.

Use reopening when a later fixture, user result, implementation result, or
decision shows that an accepted claim is wrong or incomplete.

Any reopening change should state:

- what was previously accepted;
- what new evidence contradicted or exceeded it;
- what changed;
- what remains valid;
- what tests, fixtures, expected outputs, index rows, and tracker rows changed.

If a later `JC` conflicts with an earlier one, classify the conflict before
editing:

- product: user job, target role, outcome, priority, or success signal;
- domain: concept, wording, relation, evidence handling, missing fact, or
  redaction semantics;
- architecture: dependency direction, parser/storage/UI/execution boundary,
  manifest/output identity, or support/export policy;
- implementation: prototype behavior, fixture behavior, generated output, or
  test expectation;
- public/export: identifiers, labels, relation targets, metadata,
  Markdown/JSON output, or payload/code-derived text.

Then update the owning doc or create a superseding decision. Prefer narrowing
or splitting when the earlier validated slice still holds.

## Tracker Coordination

Treat [`../status/progress-tracker.md`](../status/progress-tracker.md) as a
compact coordination surface, not a journey-local task list.

Update it when:

- a phase changes;
- a new active `JC`, route, or slice needs a link;
- a candidate moves into or out of active coordination;
- a cross-journey dependency changes.

Keep detailed reasoning in the owning `JC`, decision, prototype, or contract.

## Review Checklist

Before accepting or broadening a `JC`, check:

- Is the source or fixture boundary explicit and public-safe?
- Are evidence, inference, and future pressure separated?
- Does the slice create standalone user value?
- Are missing facts preserved without becoming mandatory producer scope?
- Are non-goals strong enough to block accidental execution, mutation,
  hardware control, environment management, or framework replacement?
- Does the prototype own the behavior it checks?
- Are public output, identifiers, labels, relation targets, and metadata
  redacted according to the declared sharing boundary?
- Are links, tracker rows, fixtures, expected outputs, and tests updated
  together when behavior changes?
