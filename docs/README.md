# Scopecat Docs

`docs/` is Scopecat's durable project memory. It keeps product direction,
research conclusions, problem framing, decisions, and user documentation when
introduced.

Start here for the top-down reading path. Use [`index.md`](index.md) only as a
flat navigation map when you already know which owner you need.

## Where To Find Current State

- Current product direction:
  [`product/direction.md`](product/direction.md)
- Current target product journeys and use cases to prove:
  [`product/target-journeys.md`](product/target-journeys.md)
- Current target product capabilities, maturity, evidence, and advancement
  questions:
  [`product/target-capabilities.md`](product/target-capabilities.md)
- Current product adoption strategy:
  [`product/adoption-strategy.md`](product/adoption-strategy.md)
- Current brownfield as-is assessment:
  [`brownfield/current-state-assessment.md`](brownfield/current-state-assessment.md)
- Current brownfield transition architecture:
  [`brownfield/transition-architecture.md`](brownfield/transition-architecture.md)
- Current brownfield migration strategy and roadmap:
  [`brownfield/migration-strategy.md`](brownfield/migration-strategy.md) and
  [`brownfield/migration-roadmap.md`](brownfield/migration-roadmap.md)
- Current brownfield risk register:
  [`brownfield/risk-register.md`](brownfield/risk-register.md)
- Current decision register:
  [`decisions/register.md`](decisions/register.md)
- Current cross-document traceability map:
  [`traceability.md`](traceability.md)
- Current use case validation state, evidence scopes, and composition gaps:
  [`engineering/workflow-validation-map.md`](engineering/workflow-validation-map.md)
- Current maturity vocabulary:
  [`engineering/delivery-maturity-model.md`](engineering/delivery-maturity-model.md)
- Current live implementation owners:
  [`engineering/implementation-register.md`](engineering/implementation-register.md)
- Current route-local prototype boundaries:
  [`engineering/prototype-boundaries/README.md`](engineering/prototype-boundaries/README.md)
- Active execution work should live in issues, PRs, or branch-specific working
  notes when implementation starts rather than this landing page.

## Read Top Down

For product and implementation direction:

1. [`product/README.md`](product/README.md) for product docs, then
   [`product/direction.md`](product/direction.md) for product direction,
   long-term boundaries, and non-goals.
2. [`product/target-journeys.md`](product/target-journeys.md) for target user
   journeys, workflows, and use cases to prove.
3. [`product/target-capabilities.md`](product/target-capabilities.md) for product
   capabilities, maturity, supporting evidence, and open advancement
   questions.
4. [`product/adoption-strategy.md`](product/adoption-strategy.md) for how users
   start adopting Scopecat.
5. [`brownfield/README.md`](brownfield/README.md) for as-is lab context,
   transition architecture, migration strategy, migration roadmap, and risk
   register.
6. [`decisions/README.md`](decisions/README.md) for decision type rules,
   current decision status, and decision-record templates.
7. [`traceability.md`](traceability.md) for current-state to target journey,
   capability, validation, and implementation traceability.
8. [`engineering/README.md`](engineering/README.md) for delivery maturity,
   workflow validation, implementation ownership, and promotion governance.
9. [`engineering/workflow-validation-map.md`](engineering/workflow-validation-map.md)
   to find use case validation state, evidence scopes, missing seams, and next
   validation questions.
10. [`engineering/implementation-register.md`](engineering/implementation-register.md)
   to find live implementation owners and their module/boundary detail docs.
11. [`engineering/prototype-boundaries/README.md`](engineering/prototype-boundaries/README.md) and the owning module
   README for live implementation boundaries and API details.

For new discovery work:

1. [`evidence/evidence-register.md`](evidence/evidence-register.md) and
   [`evidence/method.md`](evidence/method.md) for stable evidence claims and
   evidence rules.
2. [`discovery/problem-briefs/README.md`](discovery/problem-briefs/README.md)
   for problem framing.
3. [`discovery/README.md`](discovery/README.md) for discovery route, slice,
   policy, and synthesis navigation.

## Editing Rules

Keep this README focused on top-down reading. Authoring and AI-agent rules live
in [`AGENTS.md`](AGENTS.md); the PR drift checklist lives in
[`engineering/pr-documentation-drift-checklist.md`](engineering/pr-documentation-drift-checklist.md).
