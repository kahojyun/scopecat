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
[`../evidence/inventory.md`](../evidence/inventory.md)
for `EV-###`, `PN-###`, `TP-###`, and `JC-###` source material. Use
[`../journeys/jc-001/README.md`](../journeys/jc-001/README.md) as an earned exemplar, not as a template
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
| Product accepted | Enough user and product evidence exists to treat the journey or adoption route as part of product direction. | Future scope can skip decision gates. |
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
| Tracker phase | `Ready`, `Promoted`, `Accepted`, `Transitional`, `Quarantined` | Where a coordination track or inventory item sits in the progress tracker. | Use in [`../status/progress-tracker.md`](../status/progress-tracker.md). |
| Index descriptor | `Active tracker`, `First-slice record`, `Evidence owner` | How a reader should navigate the document set. | Use in [`../index.md`](../index.md) and README entry points. |

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
| Status/index | Changes status, ownership, entry-point role, or retention decision. | Update document status, [`../index.md`](../index.md), and any relevant tracker or research index. |

## Prototype Boundary Control

Prototype hardening should make the prototype's accepted responsibility clearer,
not turn every review finding into a new responsibility.

Before starting a review-fix loop on a prototype, write down the prototype's
owner boundary:

- what data, format, or behavior the prototype owns;
- what is fixture input produced by another workflow;
- what is only a consumer mock, such as a plotter, GUI, notebook, or export
  adapter stand-in;
- what outputs are validation artifacts rather than product artifacts;
- what user-controlled or arbitrary files the prototype explicitly does not
  parse, sanitize, secure, execute, or normalize.

When review finds a defect, classify it before fixing:

| Finding class | Fix in prototype? | Example handling |
| --- | --- | --- |
| Owned contract | Yes. | Reader-owned manifest fields, relation consistency, or Scopecat-managed data format checks fail unclearly. |
| Fixture input | Usually no. | Export-produced redaction status is missing; decide whether the fixture or export-flow contract should supply it. |
| Consumer mock | Only enough for smoke testing. | Plotting needs title, axis labels, and series data; reader should emit a plot spec, while the mock plotter consumes it. |
| Caller behavior | Usually no. | Caller chooses an output path, runs analysis code, or writes files after reading the snapshot. |
| Arbitrary user artifact | Usually no. | User-attached CSV, binary arrays, PDFs, notebooks, scripts, or sidecars need domain-specific adapters before Scopecat owns parsing. |
| Security or sharing policy | No unless the prototype is explicitly that policy owner. | Redaction, publishability, permission, and malicious local-user defenses belong to their owning workflow or decision. |

If a finding falls outside the owner boundary, prefer one of these responses
over adding defensive code:

- record it as an export, adapter, GUI, plotter, or policy responsibility;
- add a small note to the prototype scope's non-goals or lessons learned;
- replace broad defensive tests with one narrow smoke test for the owned
  contract;
- delete tests that only prove behavior of a mock, a caller-selected output
  path, or arbitrary user-provided file parsing.

A prototype may still add checks for malformed input, but those checks should
match the responsibility it claims. Do not grow a reader into a redaction
system, a generic parser, a plotting engine, a permission system, or an output
sandbox just because review found cases those systems would need to handle.

### Review Priority DoD

Prototype and fixture review is not a mandate to fix every plausible edge case.
Use finding priority to protect the current decision, not to turn one fixture
into a product framework.

| Priority | Default handling at prototype stage | Examples |
| --- | --- | --- |
| P1 | Must fix before relying on the prototype or fixture result. | Public or fixture redaction leak; canonical happy path fails; fixture acceptance gives a false pass; declared owner boundary is contradicted; current-scope destructive or security issue. |
| P2 | Fix only when it protects the current boundary or removes a repeated root cause. Otherwise record as follow-on schema, product, adapter, or fixture-diversity work. | Reader-owned manifest field leaks into output; relation consistency is ambiguous; status semantics are internally contradictory; multiple reviewers find the same owned-contract gap. |
| P3 | Usually do not fix during hardening. Record only if it clarifies a future schema or fixture. | Extra defensive validation, nicer error messages, mock robustness, uncommon malformed input outside the fixture claim. |
| P4 | Do not fix unless already editing the same line for a higher-priority issue. | Style, naming, small refactors, optional cleanup. |

Treat a P2 as in scope only when all of these are true:

- the finding is inside the prototype's written owner boundary;
- the clean fix does not add a new owner responsibility;
- the finding can affect the current fixture conclusion, reader output, or
  stated acceptance claim;
- the rule is unlikely to be overturned by the next obvious fixture variant, or
  it is clearly marked as fixture-local.

Treat a P2 as backlog when any of these are true:

- the fix depends on a product decision that the current fixture cannot answer;
- the finding comes from generalizing one fixture into a universal contract;
- the fix belongs to export, GUI, plotting, redaction, arbitrary artifact
  parsing, support policy, permissions, or caller behavior;
- the fix would mostly reimplement a schema/model library without increasing
  confidence in the current journey decision.

### Hardening Stop Rule

Before a review-fix loop begins, state the maximum review budget. A typical
prototype hardening pass should stop after:

- all P1 findings are fixed or explicitly block the work;
- one repeated P2 root cause is fixed across docs, fixture, implementation, and
  tests;
- at most two or three additional P2 root causes are fixed when the fixes are
  small and clearly inside the written boundary.

Stop the loop and create follow-on work when reviewers keep finding new schema
edge cases rather than the same root cause. The follow-on work should usually
be one of:

- add a different fixture shape;
- write or revise the prototype scope boundary;
- create a JSON Schema, Pydantic model, or other explicit model spike;
- record a product or architecture decision question;
- defer the issue until user validation or a later journey exercises it.

Do not keep hardening a single fixture until no reviewer can imagine another
P2. That optimizes for local completeness, not product learning.

### Contract Promotion DoD

A rule found during prototype review is not automatically a reusable product
contract. Promote it only when it has enough evidence for its intended level.

| Level | Promotion requirement |
| --- | --- |
| Fixture-local rule | The rule protects this fixture's acceptance claim, and the scope doc names it as local to this prototype. |
| Prototype contract | The rule is needed by the prototype owner boundary and has positive and negative tests. |
| Reusable domain contract | The rule survives at least two materially different fixture shapes or one fixture plus direct user/product validation. |
| Architecture or product contract | The rule changes ownership, dependency direction, export/read behavior, UI behavior, or user workflow; create or update an accepted decision before broad implementation. |

When a future fixture may overturn a rule, prefer wording such as
`fixture-local`, `current prototype assumes`, or `deferred product decision`
instead of encoding it as a broad contract. Fixture diversity usually has
higher value than adding more edge-case checks to one prototype.

## Decision Record And Optional Artifacts

Use the smallest durable record that lets a reviewer understand the choice,
evidence basis, validation boundary, and next step.

```text
Evidence owner
  -> source-map gate
  -> minimum journey decision record
  -> optional promotion surfaces when earned
```

Optional promotion surfaces include product-value route placement,
design-pressure extraction, validation slice, concepts and contracts, spike or
prototype scope, accepted decision, and ownership pass. These are not a
checklist to complete. Create one only when it has a durable reader, removes
ambiguity that blocks the next decision, or prevents a later implementation or
review from depending on hidden reasoning. An optional surface stops being
optional when implementation, architecture boundary changes, public output,
fixture behavior, generated artifacts, or accepted scope depends on it.

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
   [`../evidence/inventory.md`](../evidence/inventory.md),
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

### Experience Context Versus Validation Slice

A `JC-###` may mention the complete experience to explain why its slice
matters, but only its selected validation slice should become prototype scope.
Adjacent moments stay as context until a narrower journey, prototype, or
decision document promotes them.

Use [`../strategy/experience-map.md`](../strategy/experience-map.md) for experience
pressure that spans several journeys or keeps reappearing as future scope in
narrower docs. If the pressure changes accepted scope, fixture checks, owner
boundaries, API/schema/UI/storage behavior, execution, mutation, or hardware
semantics, move the decision to the narrower owner before implementation
depends on it.

### Design Pressure Versus Capability Ownership

Treat design pressure as evidence-linked design memory, not as an accepted
capability map. It may preserve a useful intent such as declarative plan
preview, code and dependency provenance, runtime boundary evidence, execution
readiness, settings/context evidence, or analysis lineage.

Do not promote a design-pressure label into capability ownership just because a
journey mentions it. Promote only when a later journey, prototype, or
architecture decision shows that a durable owner, contract, or product surface
is needed.

When writing a `JC` document:

- name adoption paths by user-visible product value;
- name design pressure by the fact, evidence, or boundary it preserves;
- keep historical capability names in research or as explicitly historical
  vocabulary only;
- keep missing facts as read-side report output unless a later decision accepts
  explicit source or producer support;
- avoid creating subsystem docs, capability maps, or owner routing before the
  validation slice needs them.

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

### Structured Sharing Boundary

Treat redaction as an owned workflow, not as a universal string-scanning
feature. Use the project-level complexity boundary in
[`../strategy/vision.md`](../strategy/vision.md): export or publish workflows own redaction decisions;
readers, analysis APIs, and consumer mocks do not scan payloads or certify
public safety unless they are explicitly the redaction owner; arbitrary free
text, arbitrary file payloads, and lab-specific keyword lists require
user-provided profiles or a dedicated workflow.

For `JC` source maps and fixtures, record which workflow owns redaction before
adding redaction checks. Public fixtures and docs should use fixture-authored
public handles, not real private identifiers.

For local path fields that cross a sharing or export boundary, prefer replacing
the whole path with an explicit status or opaque reference. Do not preserve
path suffixes by default; filenames, folder names, drive or share names,
usernames, project codes, and sample labels can all carry private context. If a
portable reference is needed, use an artifact ID, source-system ID, or opaque
asset URI instead of the original path. Keep original local paths only in
internal full-fidelity records or local indexes whose boundary allows them.

If a workflow claims automatic redaction, it must name the scope, such as
`structured path fields only`, `manifest metadata only`, or `user-provided
keyword profile`. Avoid broad claims such as `public-safe` or `redacted` unless
the owning workflow has validation for the stated boundary.

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
  improve a journey fixture.
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

Promoted journey documents should keep the full current-state spine visible
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
  design-pressure or capability-gap questions. Keep baseline capabilities as
  substrate or validation detail.
- Promote latent or future pressure only when the selected fixture or user
  validation proves it materially supports or blocks the journey.
- Keep calibration write-back, setup/device mutation, parameter-memory
  authority, rollback, environment mutation, support export, and device control
  out of accepted scope until a later decision accepts them.
- Treat behavioral and scaling priors as a role-play method, not as an
  independent reason to reorder pain ranking.
- Do not update vision or personas only from a technically validated fixture.

## Acceptance Gates

### Evidence To Journey Readiness

A future evidence pass is ready for source mapping and journey drafting when:

- major journey candidates link to evidence, source support, or explicit
  assumptions, with validation routes for direct, inferred, latent,
  interview-driven, and future/ADR pressure;
- claim support, source coverage, and Scopecat leverage are separated so
  confidence cannot silently become journey priority;
- top-level pain narratives decompose into smaller `PN` rows, and pain, JTBD,
  capability-gap, adoption-guardrail, and baseline statements are separated
  before journey ranking;
- the first source-map traceability is explicit enough to prevent a vague
  single-run reopen story;
- the leading journey candidate is identified with clear boundaries, while
  hypotheses, future pressure, ADR-gated items, and anti-patterns remain outside
  accepted scope;
- role-play outputs, behavioral/scaling priors, external framework baselines,
  declared physical context, manual metadata ROI, portability, and public
  redaction constraints are visible without being promoted into broad product
  scope;
- advanced lineage and design-pressure gap cases remain validation cases unless
  the selected fixture requires them.

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

### Shared Tracker Coordination

Treat the near-term section of
[`../status/progress-tracker.md`](../status/progress-tracker.md)
as a shared coordination surface, not as a journey-local task list.

A `JC` PR may update the tracker when it changes a phase, adds or removes a
durable output link, records a short cross-journey coordination point, or
retires a slice that no longer matches product direction. Keep the detailed
next decision in the `JC` owner document.

Use a separate coordination PR when the change reorders global priority,
changes the accepted sequence, promotes shared contract ownership, ranks
multiple validation slices, or updates another active `JC`'s next decision. If
multiple slices need durable ranking or scheduling coordination, move that
detail into a narrower owner note and leave only links, phases, and compact
coordination points in the tracker.

### Cross-Reference KISS

Add cross-references only when they help a future reader make or review a
decision. Useful links usually point to an entry point, owning document,
required dependency, evidence source, validation artifact, or superseding
decision.

Avoid repeated historical back-links, promotion-chain boilerplate, and
bidirectional links when a `JC` README, document index, or owner document
already provides the navigation. If a link does not clarify ownership,
dependency, evidence, or status, omit it.

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
- Which design-pressure or capability-gap questions should this journey test
  first?
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
  [`../index.md`](../index.md), relevant README, research index, and
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
