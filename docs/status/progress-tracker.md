# Progress Tracker

## Purpose

Track compact cross-journey status for Scopecat. This is a coordination
surface, not a second backlog, roadmap, capability map, or journey-local task
list.

Use owner documents for durable detail:

- evidence and candidate wording: [`../evidence/inventory.md`](../evidence/inventory.md)
- product direction: [`../strategy/vision.md`](../strategy/vision.md)
- adoption route definitions: [`../strategy/adoption-routes.md`](../strategy/adoption-routes.md)
- experience placement: [`../strategy/experience-map.md`](../strategy/experience-map.md)
- `JC` process: [`../standards/jc-operating-standard.md`](../standards/jc-operating-standard.md)

## Coordination Phases

This tracker uses compact coordination labels only: `Not Started`, `Drafting`,
`Provisional`, `Validating`, `Ready`, `Accepted`, `Quarantined`, and
`Deferred`.

Do not infer validation detail from a tracker phase. Use
[`../standards/jc-operating-standard.md`](../standards/jc-operating-standard.md)
for validation status meaning, and put acceptance criteria, fixture results,
reopening criteria, and skipped review prompts in the owning journey, decision,
prototype, or contract.

## Current Focus

| Item | Phase | Owner | Coordination note |
| --- | --- | --- | --- |
| `JC-001` passive evidence view | Accepted | [`../journeys/jc-001/README.md`](../journeys/jc-001/README.md) | First accepted slice. Keep reopen or extension detail in the owning decision, contract, or prototype document before updating shared coordination. |
| `JC-002` selected-run analysis handoff | Validating | [`../journeys/jc-002/README.md`](../journeys/jc-002/README.md) | Journey record and snapshot boundary are draft; the fixture-backed prototype is validating whether the boundary can become accepted. |
| Product-value route hypotheses | Provisional | [`../strategy/adoption-routes.md`](../strategy/adoption-routes.md) | Strategy owns route definitions; this tracker only reflects that they are provisional. |
| Future candidate rows | Not Started / Deferred | [`../evidence/inventory.md`](../evidence/inventory.md) | Canonical `JC` candidate wording and boundaries stay in the evidence owner until a journey-specific owner is created. `Not Started` means no promoted journey owner; draft evidence fixture probes may still exist outside active coordination. |

## Validation Slice Coordination

Active slices:

| Slice | Owner | Phase | Coordination note |
| --- | --- | --- | --- |
| Existing run/work bundle to explainable context bundle | [`../journeys/jc-001/decisions/passive-evidence-view.md`](../journeys/jc-001/decisions/passive-evidence-view.md) | Accepted | Backed by the accepted passive evidence-view decision. |
| Selected high-value runs to analysis handoff package | [`../journeys/jc-002/README.md`](../journeys/jc-002/README.md) | Validating | Journey record and snapshot boundary are draft; current prototype validates a fixture-scale handoff boundary only. |

Candidate dependencies to promote only if an active slice needs them:

| Candidate | Owner | Phase | Coordination note |
| --- | --- | --- | --- |
| `JC-015` | [`../evidence/inventory.md`](../evidence/inventory.md) | Not Started | Promote earlier only if `JC-002`, `JC-011`, or `JC-016` needs realistic recorded inputs. |
| `JC-016` | [`../evidence/inventory.md`](../evidence/inventory.md) | Not Started | Promote only if bounded runtime handoff becomes an active validation need. |

Use the dependency-promotion prompts in
[`../standards/jc-operating-standard.md`](../standards/jc-operating-standard.md)
before moving a candidate into active coordination.

All other candidate rows and parking-lot pressure live in
[`../evidence/inventory.md`](../evidence/inventory.md) until they need active
coordination. Draft evidence probes such as
[`../evidence/pain-discovery-fixtures.md`](../evidence/pain-discovery-fixtures.md)
do not change tracker phase unless a `JC`, route, or validation slice moves
into shared coordination.

## Review Rule

Update this tracker only when shared coordination changes:

- a phase changes;
- a new active `JC`, route, or slice needs a link;
- a candidate moves into or out of active coordination;
- a cross-journey dependency changes.

Keep per-`JC` next decisions in that `JC`'s README, decision, prototype, or
contract.
