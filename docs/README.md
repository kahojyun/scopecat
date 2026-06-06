# Scopecat Docs

`docs/` is Scopecat's durable project memory. It keeps product outcomes,
problem framing, decisions, architecture, engineering ownership, and user
documentation when introduced.

Start here for the top-down reading path. Use [`index.md`](index.md) only as a
flat navigation map when you already know which owner you need.

## Where To Find Current State

- Product vision, success metrics, canonical journey/use-case index,
  capabilities, and adoption strategy:
  [`product/README.md`](product/README.md)
- Brownfield current state, transition, migration, and risks:
  [`brownfield/README.md`](brownfield/README.md)
- Initial domain model, context map, and architecture boundaries:
  [`architecture/README.md`](architecture/README.md)
- Architecture decision record index and rules:
  [`adr/README.md`](adr/README.md)
- Engineering maturity, validation, and implementation ownership:
  [`engineering/README.md`](engineering/README.md)
- Fixture and expected-output policy:
  [`testing/fixture-policy.md`](testing/fixture-policy.md)
- Discovery problem framing and historical validation evidence:
  [`discovery/README.md`](discovery/README.md)
- Active execution work should live in issues, PRs, or branch-specific working
  notes when implementation starts rather than this landing page.

## Read Top Down

For product vision, outcomes, and implementation direction:

1. [`product/README.md`](product/README.md) for product docs, then
   [`product/vision.md`](product/vision.md) for product vision.
2. [`product/success-metrics.md`](product/success-metrics.md) for success
   metrics, outcome signals, promotion checks, and anti-metrics.
3. [`product/target-journeys.md`](product/target-journeys.md) for the
   canonical journey and use case index.
4. [`product/target-capabilities.md`](product/target-capabilities.md) for product
   capabilities, maturity, supporting evidence, and open advancement
   questions.
5. [`product/adoption-strategy.md`](product/adoption-strategy.md) for how users
   start adopting Scopecat.
6. [`brownfield/README.md`](brownfield/README.md) for as-is lab context,
   transition architecture, migration strategy, migration roadmap, and risk
   register.
7. [`architecture/README.md`](architecture/README.md) for the initial
   architecture model, domain concepts, context map, and boundary lens.
8. [`adr/README.md`](adr/README.md) for ADR admission rules, flat record
   layout, current ADR status, and templates.
9. [`engineering/README.md`](engineering/README.md) for delivery maturity,
   workflow validation, implementation ownership, and promotion governance.
10. [`engineering/workflow-validation-map.md`](engineering/workflow-validation-map.md)
   to find validation evidence, missing seams, and next validation questions
   for canonical use cases.
11. [`engineering/implementation-register.md`](engineering/implementation-register.md)
   to find live implementation owners and their module/boundary detail docs.
12. [`engineering/prototype-boundaries/README.md`](engineering/prototype-boundaries/README.md) and the owning module
   README for live implementation boundaries and API details.

For new discovery work:

1. [`discovery/problem-briefs/README.md`](discovery/problem-briefs/README.md)
   for problem framing.
2. [`discovery/README.md`](discovery/README.md) for discovery problem framing
   and historical validation evidence.

## Editing Rules

Keep this README focused on top-down reading. Authoring and AI-agent rules live
in [`AGENTS.md`](AGENTS.md); the PR drift checklist lives in
[`engineering/pr-documentation-drift-checklist.md`](engineering/pr-documentation-drift-checklist.md).
