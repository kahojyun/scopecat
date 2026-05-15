# Progress Tracker

## Purpose

Track compact cross-journey status for Scopecat. This is a coordination
surface, not a second backlog, roadmap, capability map, or journey-local task
list.

Use owner documents for durable detail:

- evidence and candidate wording: [`../evidence/inventory.md`](../evidence/inventory.md)
- product direction: [`../strategy/vision.md`](../strategy/vision.md)
- experience placement: [`../strategy/experience-map.md`](../strategy/experience-map.md)
- `JC` process: [`../standards/jc-operating-standard.md`](../standards/jc-operating-standard.md)

## Phase Legend

Use the status language in
[`../standards/jc-operating-standard.md`](../standards/jc-operating-standard.md)
for validation meaning. This tracker uses phase labels only for coordination.

| Phase | Meaning |
| --- | --- |
| Not Started | No durable owner exists yet. |
| Drafting | Early durable artifact exists, but scope or evidence confidence is still low. |
| Provisional | Evidence pressure is explicit, but not accepted as a durable route, contract, or decision. |
| Validating | Being checked against evidence, interviews, fixtures, or prototypes. |
| Ready | Good enough to guide the next analysis or design step. |
| Accepted | Decision-grade; downstream work may depend on the owning decision until a reopening trigger fires. |
| Quarantined | Research input preserved for evidence, pressure, or vocabulary, not accepted as product plan or scope. |
| Deferred | Intentionally postponed. |

## Current Focus

| Item | Phase | Owner | Coordination note |
| --- | --- | --- | --- |
| `JC-001` passive evidence view | Accepted | [`../journeys/jc-001/README.md`](../journeys/jc-001/README.md) | First accepted slice. Keep reopen or extension detail in the owning decision, contract, or prototype document before updating shared coordination. |
| `JC-002` selected-run analysis handoff | Validating | [`../journeys/jc-002/README.md`](../journeys/jc-002/README.md) | Journey record and snapshot boundary are draft; the fixture-backed prototype is validating whether the boundary can become accepted. |
| Product-value route hypotheses | Provisional | Coordination here; placement context in [`../strategy/experience-map.md`](../strategy/experience-map.md) | Routes are named by standalone user value. Durable route definitions should move to `../strategy/adoption-routes.md` only if they outgrow this coordination view. |
| Future candidate rows | Not Started / Deferred | [`../evidence/inventory.md`](../evidence/inventory.md) | Canonical `JC` candidate wording and boundaries stay in the evidence owner until a journey-specific owner is created. |

## Product-Value Route Hypotheses

These are compact route hypotheses, not a capability map, roadmap, or product
ownership model.

| Route hypothesis | Touched `JC` rows | Phase | Standalone value being tested |
| --- | --- | --- | --- |
| Run history and analysis handoff | `JC-001`, `JC-002`, `JC-006`, `JC-015` | Provisional | Open, understand, reopen, select, package, and later trace measurement work without replacing acquisition code. |
| Method and code portability diagnostics | `JC-004`, `JC-008`, `JC-013` | Not Started | Explain copied notebooks, scripts, runnable configuration, known-good sources, drift, and dry-run readiness before deployment or managed execution. |
| Experiment intent and readiness | `JC-007`, `JC-008`, `JC-016` | Not Started | Preview, diff, freeze, and mock-check plan or queue intent before one bounded runtime handoff is considered. |
| Calibration and parameter review | `JC-003`, `JC-011`, `JC-012`, `JC-016` | Provisional | Review calibration, parameter, declared-context, and advisory evidence before mutation or bounded apply. |
| Trust, diagnostics, and comparability | `JC-009`, `JC-010`, `JC-012` | Provisional | Compare known-good references, current bundles, valid-looking runs, setup states, samples, or method variants without claiming equivalence. |
| Analysis and claim lineage | `JC-002`, `JC-006`, `JC-014` | Not Started | Trace figures, fits, reports, and claims back to source runs, processing choices, corrections, exclusions, and ambiguity. |

Do not promote runtime ownership or managed execution into standalone adoption
routes until a lab can get useful value from adopting them alone. For now they
are boundary pressure: runtime owner, supplied bounds, readiness, stop
behavior, failure policy, audit records, and the decision that Scopecat does
not own hardware safety limits unless an accepted runtime decision says
otherwise.

## Validation Slice Coordination

Active slices:

| Slice | Owner | Phase | Coordination note |
| --- | --- | --- | --- |
| Existing run/work bundle to explainable context bundle | [`../journeys/jc-001/decisions/passive-evidence-view.md`](../journeys/jc-001/decisions/passive-evidence-view.md) | Accepted | Backed by the accepted passive evidence-view decision. |
| Selected high-value runs to analysis handoff package | [`../journeys/jc-002/README.md`](../journeys/jc-002/README.md) | Validating | Journey record and snapshot boundary are draft; current prototype validates a fixture-scale handoff boundary only. |

Candidate dependencies to promote only if an active slice needs them:

| Slice | Owner | Phase | Coordination note |
| --- | --- | --- | --- |
| Ordinary Python script to durable measurement record | `JC-015` candidate | Not Started | Substrate candidate to promote earlier if `JC-002`, `JC-011`, or `JC-016` needs realistic recorded inputs. |
| One reviewed package to one lab-owned runtime for one bounded local run | `JC-016` candidate | Not Started | Runtime-handoff candidate only; not generic scheduling, resource management, rollback, or autonomous calibration platform scope. |

Parking lot, not active coordination:

| Candidate pressure | Canonical rows |
| --- | --- |
| Known-good diagnostics and scientific comparability | `JC-009`, `JC-010` |
| Declared setup or local schema value | `JC-012` |
| Analysis-impact lineage | `JC-014` |
| Plan preview, parameter snapshots, copied-code identity, dry-run packages | `JC-004`, `JC-007`, `JC-008`, `JC-013` |
| Resource leases, managed execution, and remote dry run | Deferred; needs a narrower owner and accepted safety/runtime decisions before active tracking. |

## Review Rule

Update this tracker only when shared coordination changes:

- a phase changes;
- a new active `JC`, route, or slice needs a link;
- a candidate moves into or out of active coordination;
- a cross-journey dependency changes.

Keep per-`JC` next decisions in that `JC`'s README, decision, prototype, or
contract.
