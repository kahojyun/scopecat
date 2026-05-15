# Progressive Adoption Progress Tracker

## Purpose

Track durable product and architecture progress for Scopecat without turning
early work into a premature subsystem scaffold.

Current state: `JC-001` has an accepted passive evidence-view decision, a
static-analysis spike, a two-fixture read-only prototype scope, a
fixture-validated manifest/public-output contract, and a provisional capability
ownership pass for the first wedge. `JC-002` now has a drafting document set
and a fixture-backed read-only handoff snapshot prototype. The current decision
point is whether the `JC-002` fixture is strong enough to promote an accepted
prototype boundary or whether another lab scenario should challenge it first.
This tracker is active. Unpromoted W3+ adoption ladders, migration wedges,
capability names, and contract ideas remain hypotheses until a selected W2
journey promotes them.

Keep this tracker compact. It may hold the current phase table, the current
decision point, and small hypothesis inventories while there is only one active
accepted wedge. When multiple journeys, adoption ladders, migration wedges,
baseline-capability analyses, or shared contracts become active, move the
durable detail into a narrower owner document and leave only phase and links
here.

This tracker is organized around progressive platform adoption:

```text
Journey-first discovery
  -> product-value adoption ladders
  -> thin vertical migration wedges
  -> contract-first architecture
  -> subsystem specs only when needed
```

## Phase Legend

The tracker uses phase labels for workstreams and inventories.

| Phase | Meaning |
| --- | --- |
| Not Started | No durable artifact exists yet. |
| Drafting | Early durable artifact exists, but confidence is low. |
| Provisional | Evidence pressure is explicit, but the project has not promoted it into the next durable map or adoption plan. |
| Validating | Being checked against evidence, interviews, or spikes. |
| Ready | Good enough to guide near-term implementation or downstream docs. |
| Promoted | Moved from a narrower working note into the durable product/architecture record. |
| Accepted | Decision-grade; downstream work may depend on it until a reopening trigger fires. |
| Transitional | Extracted research kept temporarily until useful claims move into narrower owner docs. |
| Quarantined | Research input preserved for evidence, pressure, or vocabulary, not accepted as product plan or scope. |
| Deferred | Intentionally postponed. |

## Decision Quality Bar

A phase is complete when it creates the smallest durable artifact that can
support the next product or architecture decision. Each promoted artifact should
state:

- the decision it supports;
- the evidence basis, with direct evidence, inference, baseline comparison, and
  future pressure kept separate;
- the next consumer document or implementation decision;
- the explicit non-goals or deferred scope;
- the reopening trigger.

Do not expand an earlier-phase artifact just because later-phase pressure
exists. Convert that pressure into a new validation route unless it directly
falsifies the accepted artifact.

## Tracked Durable Inputs

This table tracks phase-relevant inputs only. Use
[`document-index.md`](document-index.md) for general navigation and document
ownership.

| Input | Phase | Notes |
| --- | --- | --- |
| Documentation policy | Ready | Captured in `README.md` and `AGENTS.md`. |
| Project vision and boundaries | Drafting | `vision.md` states current project-level direction, progressive adoption constraints, explicit recording and complexity ownership boundaries, and clear non-goals without becoming a roadmap, PRD, capability map, or architecture decision. |
| Automation architecture notes | Quarantined | Stored as research input; contains broad capability-pressure hypotheses that must be revalidated without accepting subsystem order or scaffolding. |
| Research acceptance-readiness triage | Transitional | `research/extracted/research-acceptance-readiness-triage.md` separates accepted guardrails, evidence, inferences, adoption hypotheses, future pressure, ADR-gated items, and directions not to accept upfront. |
| Experimental lab workflow reference | Quarantined | `research/extracted/experimental-lab-workflow-reference.md` preserves public-safe lab workflow intent for gap discovery without promoting legacy artifact shapes into product scope. |
| Evidence and pain-point inventory | Ready | `evidence-and-pain-point-inventory.md` is the W1 owner. `JC-001` has been promoted into the first-wedge document set. |
| Product experience map | Drafting | `product-experience-map.md` owns complete-experience shape, experience-step labels, and cross-journey coverage gaps without becoming a product plan or prototype scope. |
| JC-001 first-wedge document set | Ready | `jc-001/README.md` owns the detailed reading order for the first accepted wedge. |
| JC-002 analysis handoff document set | Validating | `jc-002/README.md` owns the selected-run handoff journey and links to the first fixture-backed prototype. |

## Workstreams

| ID | Workstream | Phase | Durable Output | Exit Criteria |
| --- | --- | --- | --- | --- |
| W1 | Evidence and pain points | Ready | `evidence-and-pain-point-inventory.md` | Major claims link back to interview notes, codebase observations, source coverage, explicit assumptions, or clearly labeled blind-persona adoption pressure; behavioral/scaling priors are separated from evidence; pain, JTBD, capability-gap, guardrail, and baseline statements are distinguished; top-level pain narratives decompose into foundational pain points with visibility and validation route. |
| W2 | End-to-end journeys | Ready | `jc-001/jc-001-work-bundle-explanation-journey.md` | At least one current-state and future-state journey is written across capability boundaries. |
| W3 | Adoption ladders | Provisional | `jc-001/jc-001-capability-adoption-extraction.md` | JC-001 adoption pressure is explicit without promoting a broader adoption plan; promote to drafting after a product or architecture decision tests whether the same adoption pressure needs durable ownership. |
| W4 | Migration wedges | Ready | `jc-001/jc-001-existing-bundle-to-explainable-context-wedge.md` | The accepted `JC-001` passive evidence-view wedge is ready; broader wedge ranking remains future W4 work. |
| W5 | Capability map | Provisional | `jc-001/jc-001-passive-evidence-view-capability-ownership.md` | JC-001 ownership pressure is explicit without promoting a broader capability map; promote to drafting after either a small map is selected or a second journey tests the owners. |
| W6 | Cross-capability contracts | Ready | `jc-001/jc-001-concepts-and-contracts.md` | Shared concepts, provisional owner pressure, and dependency direction are explicit for the accepted wedge. |
| W7 | Technical spikes and prototypes | Ready | `jc-001/jc-001-static-analysis-spike.md`; `jc-001/jc-001-passive-evidence-view-prototype-scope.md` | The static-analysis spike has a question, result, decision impact, and follow-up; the read-only prototype scope records two-fixture validation. |
| W8 | Decision promotion | Accepted | `jc-001/jc-001-passive-evidence-view-decision.md` | The passive evidence-view boundary is accepted at fixture scale. |

## Adoption Ladders To Define

The greenfield automation note framed early adoption around independently
useful foundational capabilities, not a monolithic replacement system. Current
docs should preserve that principle while avoiding a premature subsystem map:
an adoption ladder is a standalone product-value path. Historical capability
names are retained only as design intent when the wording still helps.

| Product-value adoption ladder | Touched `JC` rows | Phase | Standalone value | Design intent preserved |
| --- | --- | --- | --- | --- |
| Run history and analysis handoff | `JC-001`, `JC-002`, `JC-006`, `JC-015` | Provisional | Open, understand, reopen, select, package, and later trace measurement work without replacing acquisition code. | Stable run or bundle identity, durable records, lifecycle state, handoff snapshots, and campaign lineage. |
| Method and code portability diagnostics | `JC-004`, `JC-008`, `JC-013` | Not Started | Explain copied notebooks, scripts, runnable configuration, known-good sources, drift, and dry-run readiness before deployment or managed execution. | Code and dependency provenance, entrypoint identity, lockfile or environment clues, drift diagnostics, and readiness without Git hosting or environment sync. |
| Experiment intent and readiness | `JC-007`, `JC-008`, `JC-016` | Not Started | Preview, diff, freeze, and mock-check plan or queue intent before one bounded runtime handoff is considered. | Declarative scan or queue intent that can render desired state for preview and later share semantics with bounded apply. |
| Calibration and parameter review | `JC-003`, `JC-011`, `JC-012`, `JC-016` | Provisional | Review calibration, parameter, declared-context, and advisory evidence before mutation or bounded apply. | Settings, calibration, local schema, proposal, and advisory evidence before authoritative write-back. |
| Trust, diagnostics, and comparability | `JC-009`, `JC-010`, `JC-012` | Provisional | Compare known-good references, current bundles, valid-looking runs, setup states, samples, or method variants without claiming equivalence. | Conflict diagnostics, declared-context limits, comparability gaps, and known-good reference explanation without rollback or equivalence scoring. |
| Analysis and claim lineage | `JC-002`, `JC-006`, `JC-014` | Not Started | Trace figures, fits, reports, and claims back to source runs, processing choices, corrections, exclusions, and ambiguity. | Derived-artifact lineage and report impact without ELN or report generation. |

Do not promote runtime ownership or managed execution into standalone adoption
ladders until a lab can get useful value from adopting them alone. For now they
are boundary pressure: runtime owner, supplied bounds, readiness, stop
behavior, failure policy, audit records, and the decision that Scopecat does
not own hardware safety limits unless an accepted runtime decision says
otherwise.

## Candidate Migration Wedges

This tracker carries only active or near-decision wedge coordination. Canonical
candidate wording and boundaries live in
[`evidence-and-pain-point-inventory.md`](evidence-and-pain-point-inventory.md)
or a narrower `JC` owner.

Lab-management context from the workflow reference is not a migration wedge by
default. Booking, cooldown planning, shift handoff, sample inventory, safety,
training, incidents, personnel coordination, and multi-equipment scheduling may
inform readiness, lifecycle, context handles, or apply guardrails, but they
should not turn this table into a lab-operations backlog.

| Wedge | Owner | Phase | Coordination note |
| --- | --- | --- | --- |
| Existing run/work bundle to explainable context bundle | `JC-001` document set | Ready | Backed by the accepted passive evidence-view decision. |
| Starred runs to analysis handoff package | [`jc-002/README.md`](jc-002/README.md) | Validating | Decide whether the current fixture-backed prototype earns an accepted fixture-scale boundary or needs another scenario. |
| Ordinary Python script to durable measurement record | `JC-015` candidate | Not Started | Substrate candidate to promote earlier if `JC-002`, `JC-011`, or `JC-016` needs realistic recorded inputs. |
| One reviewed package to one lab-owned runtime for one bounded local run | `JC-016` candidate | Not Started | Runtime-handoff candidate only; not generic scheduling, resource management, rollback, or autonomous calibration platform scope. |

Candidate parking lot, not active coordination:

| Candidate pressure | Canonical rows |
| --- | --- |
| Known-good diagnostics and scientific comparability | `JC-009`, `JC-010` |
| Declared setup or local schema value | `JC-012` |
| Analysis-impact lineage | `JC-014` |
| Plan preview, parameter snapshots, copied-code identity, dry-run packages | `JC-004`, `JC-007`, `JC-008`, `JC-013` |
| Resource leases, managed execution, and remote dry run | Deferred; needs a narrower owner and accepted safety/runtime decisions before active tracking. |

For W2 validation, use the generic lab context and external-framework baseline
owned by
[`evidence-and-pain-point-inventory.md`](evidence-and-pain-point-inventory.md).
Use [`vision.md`](vision.md) for project-level adoption boundaries with
existing experiment systems.

## Near-Term Coordination

Completed path:

```text
W1 evidence inventory
  -> JC-001 journey and wedge
  -> accepted passive evidence-view decision
  -> two-fixture prototype
  -> provisional ownership pass
```

This section is a coordination surface, not the owner of every active journey's
next step. Keep per-`JC` next decisions in that `JC`'s README, scope document,
or decision record, then link from the tracker only when a status, phase, or
cross-journey dependency changes.

Active coordination points:

- `JC-002`: decide whether the handoff snapshot prototype earns an accepted
  fixture-scale boundary, needs another scenario, or should feed back into a
  small capability map with the `JC-001` ownership pass.

For parallel journey edits and promotion rules, use
[`jc-analysis-operating-standard.md`](jc-analysis-operating-standard.md). This
tracker should only carry links, phase changes, and compact cross-journey
coordination points.

## Review Cadence

Review this tracker whenever a durable product or architecture document is
created, removed, or promoted out of research.

During review:

- update phases;
- add links to durable outputs;
- retire wedges that no longer match the product direction;
- move growing ladder, wedge, baseline, or contract detail into narrower owner
  docs once it has more than one active consumer;
- avoid adding new workstreams unless they change how the project is managed.

## Guardrails

- Do not split product discovery by subsystem.
- Do not create subsystem specs before journeys, adoption ladders, and
  contracts justify them.
- Do not require full-platform adoption for any initial adoption path.
- Treat top-level pains as composition pressure, not single-ladder
  implementation requirements. A full answer may require several adoption
  ladders, but each promoted slice must validate one narrow, independently
  useful path.
- Do not let standalone adoption stories become incompatible mini-products.
- Keep each wedge narrow enough to validate with one concrete workflow.
