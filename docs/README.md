# Scopecat Docs

`docs/` is Scopecat's durable project memory. It keeps product direction,
research conclusions, problem framing, decisions, and user documentation when
introduced.

Start here for the top-down reading path. Use [`index.md`](index.md) only as a
flat navigation map when you already know which owner you need.

## Current State

- Scopecat is in engineering-prototype phase, not production-supported release.
- Current live owners are Measurement Records, Handoff, Environment Operation,
  and Parameter State route modules.
- The main composition gap is legacy measurement portable handoff: recorded
  legacy run -> selected stored measurement -> handoff package -> preview and
  import on another computer.
- Discovery docs are evidence and route posture; implementation ownership lives
  in engineering registers, prototype-boundary notes, and module READMEs.
- Production vertical slices should be promoted only from named workflow steps,
  seams, or risk questions.

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

## Current Model

Keep durable statements in the narrowest owner:

- engineering governance: [`engineering/README.md`](engineering/README.md)
- engineering phase rules: [`engineering/project-phase-model.md`](engineering/project-phase-model.md)
- workflow validation state: [`engineering/workflow-validation-map.md`](engineering/workflow-validation-map.md)
- accepted implementation slices: [`engineering/vertical-slice-register.md`](engineering/vertical-slice-register.md)
- evidence claims: [`evidence/evidence-register.md`](evidence/evidence-register.md)
- evidence interpretation: [`evidence/method.md`](evidence/method.md)
- discovery navigation: [`discovery/README.md`](discovery/README.md)
- prototype boundaries: [`engineering/prototype-boundaries/README.md`](engineering/prototype-boundaries/README.md)
- problem framing: [`discovery/problem-briefs/README.md`](discovery/problem-briefs/README.md)
- adoption routes: [`discovery/routes/adoption-routes.md`](discovery/routes/adoption-routes.md)
- discovery slice evidence: [`discovery/slices/README.md`](discovery/slices/README.md)
- cross-slice synthesis: [`discovery/synthesis/cross-slice.md`](discovery/synthesis/cross-slice.md)
- discovery deferrals: [`discovery/synthesis/shared-model-extraction-deferral.md`](discovery/synthesis/shared-model-extraction-deferral.md)
- product direction: [`product/direction.md`](product/direction.md)
- research inputs: [`evidence/research/README.md`](evidence/research/README.md)

Create validation, decision, prototype-boundary, engineering governance, or
user docs only when there is a specific durable owner and content for them.
Engineering governance docs define phase, workflow, and slice ownership rules
across routes. Prototype-boundary notes are for route-local engineering
ownership after discovery evidence starts turning into implementation work;
they should link back to discovery evidence instead of copying it wholesale.

## Editing Rules

- Update existing documents before creating new structure.
- Do not create placeholder directories, sentinel files, or broad scaffolds.
- Keep top-down orientation in this README and flat inventory in
  [`index.md`](index.md); do not make every README repeat the full document
  map.
- Mark hypotheses, accepted decisions, and open questions explicitly when the
  distinction matters.
- Keep public-facing documentation under `docs/user/` when it is introduced,
  and treat it as redacted by default.
- Docs-only wording or navigation changes may not need tests. If there are no
  remaining executable tests for the changed area, say that explicitly.
