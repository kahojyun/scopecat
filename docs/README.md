# Scopecat Docs

`docs/` is Scopecat's durable project memory. It keeps product direction,
research conclusions, problem framing, decisions, and user documentation when
introduced.

Start here for the top-down reading path. Use [`index.md`](index.md) only as a
flat navigation map when you already know which owner you need.

## Where To Find Current State

- Current workflow status and composition gaps:
  [`engineering/workflow-validation-map.md`](engineering/workflow-validation-map.md)
- Current product adoption paths:
  [`product/adoption-model.md`](product/adoption-model.md)
- Current product capabilities, maturity, evidence, and advancement questions:
  [`product/capability-map.md`](product/capability-map.md)
- Current maturity vocabulary:
  [`engineering/delivery-maturity-model.md`](engineering/delivery-maturity-model.md)
- Current live implementation owners:
  [`engineering/implementation-register.md`](engineering/implementation-register.md)
- Current route-local prototype boundaries:
  [`engineering/prototype-boundaries/README.md`](engineering/prototype-boundaries/README.md)
- Active execution work should live in issues, PRs, or branch plans rather than
  this landing page.

## Read Top Down

For product and implementation direction:

1. [`product/README.md`](product/README.md) for product docs, then
   [`product/direction.md`](product/direction.md) for product direction,
   long-term boundaries, and non-goals.
2. [`product/adoption-model.md`](product/adoption-model.md) for brownfield
   adoption paths and migration boundaries.
3. [`product/capability-map.md`](product/capability-map.md) for product
   capabilities, maturity, supporting evidence, and open advancement
   questions.
4. [`engineering/README.md`](engineering/README.md) for delivery maturity,
   workflow validation, implementation ownership, and promotion governance.
5. [`engineering/workflow-validation-map.md`](engineering/workflow-validation-map.md)
   to find the user workflow thread, validated steps, missing seams, and next
   validation question.
6. [`engineering/implementation-register.md`](engineering/implementation-register.md)
   to find live implementation owners and their module/boundary detail docs.
7. [`engineering/prototype-boundaries/README.md`](engineering/prototype-boundaries/README.md) and the owning module
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
