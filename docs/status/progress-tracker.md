# Progress Tracker

## Purpose

Track compact coordination status for Scopecat. This is not a backlog,
roadmap, capability map, or validation task list.

Use owner documents for durable detail:

- evidence claims: [`../evidence/inventory.md`](../evidence/inventory.md)
- pain packet framing: [`../evidence/pain-packets/README.md`](../evidence/pain-packets/README.md)
- product direction: [`../strategy/vision.md`](../strategy/vision.md)
- adoption route hypotheses: [`../strategy/adoption-routes.md`](../strategy/adoption-routes.md)

## Coordination Phases

This tracker uses compact coordination labels only: `Drafting`,
`Provisional`, `Validating`, `Ready`, `Accepted`, `Quarantined`, and
`Deferred`.

Do not infer validation detail from a tracker phase. Put acceptance criteria,
reference-case results, user-validation notes, reopening criteria, and skipped
review prompts in the owning evidence, strategy, validation, decision,
contract, or ADR document.

## Current Focus

| Item | Phase | Owner | Coordination note |
| --- | --- | --- | --- |
| Evidence register cleanup | Ready | [`../evidence/inventory.md`](../evidence/inventory.md) | The old candidate layer and its prototypes were removed. The inventory now owns stable evidence claims only; problem framing moved to pain packets and route hypotheses. |
| Product-value route hypotheses | Provisional | [`../strategy/adoption-routes.md`](../strategy/adoption-routes.md) | Routes remain useful as adoption-value hypotheses, but they are not implementation order or accepted scope. |
| Pain packet cleanup | Ready | [`../evidence/pain-packets/README.md`](../evidence/pain-packets/README.md) | The premature synthetic validation layer was removed. Pain packets now preserve evidence-backed failures, owner clarifications, hypotheses, and premature boundaries. |

## Active Validation Work

There is no active accepted validation target after the cleanup. Previous
prototype-heavy slices were deleted because they encoded more detail than the
current evidence model needs. Git history remains the fallback if a future
validation charter justifies reconstructing one.

## Review Rule

Update this tracker only when shared coordination changes:

- a phase changes;
- a route, problem-framing note, validation charter, or validation target needs a link;
- a candidate validation question moves into or out of active coordination;
- a cross-option or cross-validation dependency changes.

Keep detailed reasoning in the owning evidence, strategy, pain-packet,
validation, decision, or contract document.
