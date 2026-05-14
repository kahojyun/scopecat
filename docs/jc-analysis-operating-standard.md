# Journey Candidate Analysis Operating Standard

## Status

Doc ready as the operating standard for future `JC-###` analysis.

## Purpose

Define the repeatable process for selecting, drafting, validating, promoting,
reopening, and retiring journey candidates without copying the full `JC-001`
document set by default.

This document owns process. It is not a product vision, evidence inventory,
capability map, architecture decision, fixture manifest contract, redaction
policy, or subsystem spec.

Use the evidence owner
[`evidence-and-pain-point-inventory.md`](evidence-and-pain-point-inventory.md)
for `EV-###`, `PN-###`, `TP-###`, and `JC-###` source material. Use
[`jc-001/README.md`](jc-001/README.md) as an earned exemplar, not as a template
to copy wholesale.

## Status Language

Use statuses on a specific document, claim, decision, fixture, or output
contract. Do not use one broad status for a whole `JC-###` folder unless every
artifact in the folder is at the same validation level.

| Status | Use when | Does not mean |
| --- | --- | --- |
| Draft | Working text exists, but evidence, scope, or acceptance is still unstable. | Ready for implementation. |
| Doc ready | The document is internally coherent and can guide the next analysis step. | Fixture, user, or product validation exists. |
| Fixture validated | Synthetic, redacted, or high-fidelity fixture checks pass. | Real users can make better decisions from the output. |
| User validated | Representative users can complete the target task and interpret the output correctly. | Broader product direction is accepted. |
| Accepted boundary | The project accepts a scoped product, domain, or architecture boundary until reopening criteria fire. | Product-market fit, subsystem ownership, or broad capability acceptance. |
| Product accepted | Enough user and product evidence exists to treat the journey or capability as part of product direction. | Future scope can skip decision gates. |
| Provisional | Evidence pressure is explicit, but the project has not promoted it into a durable map, ownership model, or adoption plan. | Accepted boundary. |
| Deferred | The scope is intentionally postponed and needs a later evidence-backed decision. | Rejected forever. |
| Reopened | A later journey, fixture, user result, or implementation result has challenged a previous accepted claim or scope. | The whole earlier `JC` is invalid. |
| Superseded | A newer owner doc or decision replaces this artifact for future work. | The old artifact should be edited as if it never existed. |

For `JC-001` today, the passive evidence-view decision is an accepted boundary,
the prototype scope is fixture validated, and the product direction is not yet
product accepted.

### Status Crosswalk

The statuses above are validation statuses for documents, claims, decisions,
fixtures, and contracts. Tracker and index labels are navigation metadata.

| Label family | Examples | Meaning | Preferred use |
| --- | --- | --- | --- |
| Validation status | `Doc ready`, `Fixture validated`, `Accepted boundary`, `Product accepted` | How far a specific artifact, claim, fixture, or decision has been validated. | Use in `JC-###` documents and accepted decisions. |
| Tracker phase | `Ready`, `Promoted`, `Accepted`, `Transitional`, `Quarantined` | Where a workstream or inventory item sits in the progressive adoption tracker. | Use in `progressive-adoption-progress-tracker.md`. |
| Index descriptor | `Active tracker`, `First-wedge record`, `W1 evidence owner` | How a reader should navigate the document set. | Use in `document-index.md` and README entry points. |

## Change Classes

Classify durable `JC` changes before deciding follow-through:

| Class | Examples | Required follow-through |
| --- | --- | --- |
| Wording | Clarifies phrasing without changing behavior or contract. | Update the owning doc and index if status or entry-point meaning changes. |
| Product | Changes user job, target role, journey priority, or accepted outcome. | Update journey, evidence links, non-goals, validation route, and tracker status. |
| Domain | Changes concept, vocabulary, relation, evidence handling, or missing-fact semantics. | Update concepts/contracts, fixtures, expected outputs, and tests if behavior changes. |
| Architecture | Changes owner, dependency direction, redaction policy, manifest contract, parser/storage/UI/execution boundary, or support/export boundary. | Update or create an accepted decision before broadening implementation scope. |
| Fixture | Changes validation data, source-map record, redaction labels, or expected output shape. | Update the source-map record, fixture files, expected outputs, and tests together. |
| Implementation | Changes prototype behavior or generated artifacts. | Update implementation, docs, fixtures, tests, and expected outputs together. |
| Status/index | Changes status, ownership, entry-point role, or retention decision. | Update document status, `document-index.md`, and any relevant tracker or research index. |

## Decision Record And Optional Artifacts

Use the smallest durable record that lets a reviewer understand the choice,
evidence basis, validation boundary, and next step.

```text
Evidence owner
  -> source-map gate
  -> minimum journey decision record
  -> optional promotion surfaces when earned
```

Optional promotion surfaces include adoption extraction, migration wedge,
concepts and contracts, spike or prototype scope, accepted decision, and
ownership pass. These are not a checklist to complete. Create one only when it
has a durable reader, removes ambiguity that blocks the next decision, or
prevents a later implementation or review from depending on hidden reasoning.
An optional surface stops being optional when implementation, architecture
boundary changes, public output, fixture behavior, generated artifacts, or
accepted scope depends on it.

### Minimum Record Checklist

Every promoted `JC` needs a public-safe committed floor, even when full-fidelity
validation remains non-public. Here, promoted means the `JC` record is used to
guide downstream journey, fixture, prototype, tracker, architecture, or
decision work.

The committed record must identify:

- candidate ID, status, and canonical location;
- source or fixture boundary;
- public-safe source summary;
- evidence class and source coverage;
- validation boundary;
- non-goals or deferred scope;
- next decision or next consumer;
- if a non-public source-map record is used, the public-safe owner or channel,
  storage class, redaction reason, and validation facts summarized publicly.

### Starting The Next JC

For the next `JC-###`, start here:

1. Select one candidate row from
   [`evidence-and-pain-point-inventory.md`](evidence-and-pain-point-inventory.md),
   usually a `JC-###` candidate backed by concrete `PN-###` rows.
   Use the selection prompts below before committing the minimum record.
2. Create or identify the minimum source-map record before writing journey
   prose. This may be a public-safe committed document, a non-public
   full-fidelity working map, or a compact source-map section in the selection
   note when the fixture boundary is small.
3. Leave a minimum durable journey decision record after the source-map record
   shows a concrete fixture boundary. Use the minimum record checklist above
   instead of creating fixed files by default.
4. Make the record answer: why this candidate, what current-state spine, what
   future-state slice, and what validation route.
5. Split the record into separate selection, journey, contract, decision, or
   prototype documents only after length, reuse, review risk, or implementation
   dependency makes the split useful.

The `JC-001` folder shows how a candidate can accumulate later artifacts. It
is not the minimum starting packet for new journey work.

## Source-Map Gate

Draft or identify the source-map record before journey prose. Its job is to
keep the journey from becoming a vague story.

### Record Form

The required output is traceability, not a mandatory standalone public
document. Use `docs/jc-###/jc-###-source-map.md` when the redacted source map is
durable, public-safe, and likely to have more than one future reader or
consumer. Use a non-public full-fidelity working map when exact source paths,
local labels, system names, usernames, instrument identifiers, or other
private details are needed for validation. Use a compact section in the journey
selection note when only the role-stable fixture boundary needs to survive in
the repository.

### Public And Private Boundary

Do not create a separate public source-map document only to satisfy process.
If redaction would remove the validation-relevant detail or duplicate a
private working map, commit the smallest public-safe summary that supports the
journey decision. Public docs may reference a non-public source-map record only
through an abstract owner, channel, storage class, or fixture-authored redaction
handle. Do not publish exact private paths, usernames, system names, source
labels, lab labels, instrument identifiers, machine identifiers, or other
source-derived location details.

### Review Checklist

These fields are reviewer questions, not a required table schema. They may be
answered in one table, short bullets, a fixture manifest, a selection note, or
a non-public working map. Use `N/A` or omit non-core fields when the fixture
genuinely does not exercise them, but avoid promoting a journey when the
omission hides the validation boundary. For promoted records, the fixture or
anchor, source family or public handle, evidence handling, inclusion reason,
and sharing boundary are core fields; if one is absent, record why.

| Field | Capture |
| --- | --- |
| Fixture and anchor | Fixture ID plus the anchor object type, such as run, dataset, report, notebook, known-good reference, inherited folder, or work bundle. |
| Source family or public handle | Redacted source family, role-based artifact label, or fixture-authored public handle. Private validation paths belong only in non-public records. |
| Role | Artifact role, such as anchor, selected-context candidate, code candidate, generated protocol, derived artifact, report or handoff item, setup evidence, environment evidence, backup, cache, checkpoint, or unknown. |
| Status | Active, obsolete, backup, generated, cache, checkpoint, missing, stale, conflicting, or unknown. |
| Relation | Produced-by, consumed-by, derived-from, copied-from, manually selected, imported, or unknown. |
| Evidence handling | Observed, declared, inferred, unchecked, externally verified, or unsafe to inspect. |
| Inclusion reason | The `PN-###` or guardrail supported, plus the tempting interpretation this artifact must not support. |
| Sharing boundary | Internal full-fidelity diagnostic, sanitized internal handoff, external/support-boundary export, or public-safe example. |

This is source-map vocabulary, not fixture-manifest controlled vocabulary. When
a prototype defines a narrower manifest contract, use that contract for fixture
validation and keep the broader source-map record as traceability. If both are
active, add a short crosswalk from source-map value to manifest or output value
and mark behavior as accepted, rejected, or deferred.

### Artifact Handling

- When notebook fixtures are used as evidence, prefer scripted source-cell
  extraction. Use outputs, plots, tables, paths, errors, or displayed artifacts
  only when they are intentionally selected evidence. Treat execution counts,
  kernels, embedded paths, and local imports as workflow evidence, not reliable
  notebook state.
- Opaque binary artifacts such as `.pkl`, `.npy`, `.npz`, and archives should be
  cataloged by metadata, hashes, producer/consumer links, and nearby code
  before semantic claims. Do not unpickle or execute opaque artifacts just to
  improve a W2 fixture.
- Caches, checkpoints, generated bytecode, copied folders, and embedded VCS
  metadata are strong provenance and portability evidence, but should not
  become source-of-record design patterns.

## Workflow Spine And Role Lenses

Use complete notebook-like workflows to understand current state, then slice
future product scope by outcome and boundary.

```text
choose context/config
  -> run or locate measurement
  -> watch/check partial data
  -> reopen primary result
  -> find companion artifacts and context
  -> analyze, fit, or correct
  -> decide whether results affect configuration
  -> hand off or report
```

Role lenses may switch inside one journey:

| Step | Common role hats |
| --- | --- |
| Choose context/config | Operator, method author, configuration reviewer |
| Run or locate measurement | Operator, method author |
| Watch/check partial data | Operator |
| Reopen primary result | Analyst, operator |
| Find companion artifacts and context | Analyst, configuration reviewer |
| Analyze, fit, or correct | Analyst |
| Decide whether results affect configuration | Configuration reviewer, analyst |
| Hand off or report | Analyst, recipient, method author |

Promoted W2 journey documents should keep the full current-state spine visible
while scoping the future slice narrowly.

## Promotion Guidance

- Treat any future candidate as draft until it has a minimum durable journey
  decision record with evidence, boundary, non-goals, and validation route.
- Draft or identify the fixture source-map record before journey prose. If the
  selected bundle cannot identify anchor objects, artifact roles, active versus
  obsolete status, notebook source cells, opaque binary handling, and sharing
  boundaries, revise the fixture before promoting any journey.
- Use `TP-###` rows as journey seeds, then write acceptance against smaller
  `PN-###` rows with evidence, visibility, validation route, and boundaries.
- Let foundational pains drive acceptance. Let adoption-risk hypotheses and
  guardrails constrain or invalidate a journey only through fixture, interview,
  or prototype checks.
- Convert JTBD candidates into journey phrasing. Require fixtures for
  capability gaps. Keep baseline capabilities as substrate or validation
  detail.
- Promote latent or future pressure only when the selected fixture or user
  validation proves it materially supports or blocks the journey.
- Keep calibration write-back, setup/device mutation, parameter-memory
  authority, rollback, environment mutation, support export, and device control
  out of accepted scope until a later decision accepts them.
- Treat behavioral and scaling priors as a role-play method, not as an
  independent reason to reorder pain ranking.
- Do not update vision or personas only from a technically validated fixture.

## Acceptance Gates

### W1 To W2 Readiness

A future W1 pass is ready for W2 source mapping and journey drafting when:

- major journey candidates link to evidence, source support, or explicit
  assumptions, with validation routes for direct, inferred, latent,
  interview-driven, and future/ADR pressure;
- claim support, source coverage, and Scopecat leverage are separated so
  confidence cannot silently become W2 priority;
- top-level pain narratives decompose into smaller `PN` rows, and pain, JTBD,
  capability-gap, adoption-guardrail, and baseline statements are separated
  before journey ranking;
- the first W2 source-map traceability is explicit enough to prevent a vague
  single-run reopen story;
- the leading W2 candidate is identified with clear boundaries, while
  hypotheses, future pressure, ADR-gated items, and anti-patterns remain outside
  accepted scope;
- role-play outputs, behavioral/scaling priors, external framework baselines,
  declared physical context, manual metadata ROI, portability, and public
  redaction constraints are visible without being promoted into broad product
  scope;
- advanced lineage and capability-gap cases remain validation cases unless the
  selected fixture requires them.

### Product Decision Readiness

A product decision is ready when a reviewer can answer:

- the decision being made: build, validate, defer, reject, or reopen;
- target user or role and situation;
- evidence basis with confidence and source type;
- current workaround and why it is insufficient;
- concrete user outcome and success threshold;
- validation method and result, including failed or negative signals;
- accepted scope, deferred scope, non-goals, and reopening triggers;
- next consumer: implementation, architecture, research, public docs, or
  another journey.

### Domain Contract Readiness

A domain contract is ready when a reviewer can answer:

- owner document;
- allowed source and target roles;
- non-authority semantics;
- assertion basis;
- provenance or derivation mechanism;
- verification and safety state;
- freshness, absence, and missing-fact behavior;
- sharing behavior;
- fixture and expected-output coverage.

### Architecture Boundary Readiness

An architecture boundary is ready when a reviewer can answer:

- accepted boundary;
- deferred boundary;
- explicit non-goals;
- owner and dependency direction;
- implementation surface allowed now;
- parser, storage, UI, execution, hardware, mutation, support-export, and
  redaction implications;
- fixture or prototype validation;
- reopening criteria.

## Scope Reopening

Later `JC` work may extend, specialize, or reopen earlier `JC` work. It should
not quietly generalize earlier work.

Use reopening when a later fixture, user result, implementation result, or
decision shows that an existing `JC` coverage claim is wrong or incomplete.

| Reopening shape | Use when | Clean handling |
| --- | --- | --- |
| Narrow scope | Existing claim is too broad, but the validated slice remains useful. | Update the owner decision or scope doc; say what remains accepted; move excluded pressure to follow-on scope. |
| Expand scope | New evidence proves broader behavior is needed and feasible. | Add validation and a new or updated accepted decision before broadening implementation. |
| Split scope | One `JC` is carrying two jobs. | Keep the original `JC` for the validated slice; create or reference a separate `JC` for the new job. |
| Replace scope | Later evidence shows the original framing is misleading or invalid. | Mark the old artifact superseded or reopened; create a replacement decision with explicit rationale. |

Any reopening change should make clear:

- what was previously accepted;
- what new evidence contradicted or exceeded it;
- what changed;
- what remains valid;
- what tests, fixtures, expected outputs, index rows, and tracker rows changed;
- whether old fixtures still represent a valid narrower case.

## Conflict Handling

If a later `JC` conflicts with an earlier `JC`, do not hide the conflict by
making the new text appear compatible. Classify the conflict first:

- product: user job, target role, outcome, priority, or success signal;
- domain: concept, wording, relation, evidence handling, missing fact, or
  redaction semantics;
- architecture: owner, dependency direction, parser/storage/UI/execution
  boundary, manifest/output identity, or support/export policy;
- implementation: prototype behavior, fixture behavior, generated output, or
  test expectation;
- public/export: identifiers, labels, relation targets, metadata,
  Markdown/JSON output, or payload/code-derived text.

Then update the owning existing doc or create a superseding decision. Prefer
narrowing or splitting over broad replacement when the earlier validated slice
still holds.

## Selection Prompts

Use these prompts before selecting the next `JC`:

- What exact source bundle should define the validation fixture?
- What is the minimum fixture source-map record for that bundle?
- Does this journey need live inspection or new writes, or can it start as
  offline explanation plus ambiguity checks?
- Which direction-bias correction must the journey preserve?
- Which data shapes are required now, and which can stay validation cases?
- What portability and sanitization level is required for internal handoff,
  reuse on another lab machine, public docs, and support-boundary sharing?
- What handoff record helps a new or returning user continue work without
  turning Scopecat into onboarding, training, or a full ELN?
- What is the minimum evidence record that helps users without claiming
  Scopecat owns setup, parameters, notebook state, code execution, or physical
  truth?
- Which role lenses must be visible without splitting one natural workflow into
  separate role-specific journeys?
- Which top-level pain narrative seeds the journey, and which foundational
  pain points become acceptance pressure?

Use these prompts for later validation backlog:

- Which prospective-control pains are hidden by old workflow shape?
- Which latent pains need interview, fixture, or prototype validation before
  they can change journey rank?
- Which `PN` rows should become explicit JTBD statements?
- Which adoption-risk hypotheses need journey checks?
- Which behavioral or scaling priors should remain in role-play prompts?
- Which capability-gap questions should this journey test first?
- Which manually maintained physical or sample-topology fields earn their
  maintenance cost through a concrete output?
- What is the smallest versioned local schema model that avoids pretending to
  be universal?
- What is the smallest confidence or readiness display that helps users act
  without pretending to prove experiment trust?
- Can Scopecat produce recipient-appropriate diagnostics without turning into
  a ticketing or remote-support product?

## Documentation Review Checklist

Use this checklist during review. Not every item applies to every change, but a
reviewer should be able to see why skipped items are not relevant.

- status values are valid and synchronized across the document,
  [`document-index.md`](document-index.md), relevant README, research index, and
  tracker when applicable;
- new or changed durable facts have one owner doc;
- claims promoted from research preserve evidence class, source coverage,
  validation route, and non-goals;
- public/internal visibility is explicit;
- public-safe material passes redaction review for identifiers, labels,
  relation targets, metadata, Markdown/JSON payloads, and source-derived text;
- contract or behavior changes update docs, implementation, fixtures, tests,
  and expected outputs together;
- the change states what remains provisional, deferred, reopened, or superseded.
