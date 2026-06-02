# Scopecat Docs

`docs/` is Scopecat's durable project memory. It keeps product direction,
research conclusions, problem framing, decisions, and user documentation when
introduced.

Start here for the top-down reading path. Use [`index.md`](index.md) only as a
flat navigation map when you already know which owner you need.

## Where To Find Current State

- Current workflow status and composition gaps:
  [`engineering/workflow-validation-map.md`](engineering/workflow-validation-map.md)
- Current live implementation owners:
  [`engineering/vertical-slice-register.md`](engineering/vertical-slice-register.md)
- Current route-local prototype boundaries:
  [`engineering/prototype-boundaries/README.md`](engineering/prototype-boundaries/README.md)
- Active execution work should live in issues, PRs, or branch plans rather than
  this landing page.

## Read Top Down

For product and implementation direction:

1. [`product/direction.md`](product/direction.md) for product
   posture, long-term boundaries, and non-goals.
2. [`engineering/README.md`](engineering/README.md) for phase, workflow, and
   vertical-slice governance.
3. [`engineering/workflow-validation-map.md`](engineering/workflow-validation-map.md)
   to find the user workflow thread, validated steps, missing seams, and next
   validation question.
4. [`engineering/vertical-slice-register.md`](engineering/vertical-slice-register.md)
   to find the accepted implementation owner, entrypoint, tests, fixture
   boundary, and non-goals.
5. [`engineering/prototype-boundaries/README.md`](engineering/prototype-boundaries/README.md) and the owning module
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

- Update existing documents before creating new structure.
- Do not create placeholder directories, sentinel files, or broad scaffolds.
- Keep top-down orientation in this README and flat inventory in
  [`index.md`](index.md); do not make every README repeat the full document
  map.
- Do not duplicate owner inventories across README files. When adding or
  moving a document, update the nearest owner index and link to that index from
  higher levels.
- Create validation, decision, prototype-boundary, engineering governance, or
  user docs only when there is a specific durable owner and content for them.
- Keep active task queues, priorities, and implementation checklists in issues,
  PRs, or branch plans rather than this stable landing page.
- Mark hypotheses, accepted decisions, and open questions explicitly when the
  distinction matters.
- Keep public-facing documentation under `docs/user/` when it is introduced,
  and treat it as redacted by default.
- Docs-only wording or navigation changes may not need tests. If there are no
  remaining executable tests for the changed area, say that explicitly.
