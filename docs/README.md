# Scopecat Docs

`docs/` is Scopecat's durable project memory. It keeps product direction,
research conclusions, problem framing, decisions, and future user documentation
in plain Markdown.

Use [`index.md`](index.md) as the navigation map.

## Current Model

Keep durable statements in the narrowest owner:

- evidence claims: [`evidence/evidence-register.md`](evidence/evidence-register.md)
- evidence interpretation: [`evidence/method.md`](evidence/method.md)
- problem framing: [`discovery/problem-briefs/README.md`](discovery/problem-briefs/README.md)
- adoption hypotheses: [`discovery/adoption-hypotheses.md`](discovery/adoption-hypotheses.md)
- product direction: [`strategy/product-direction.md`](strategy/product-direction.md)
- research inputs: [`evidence/research/README.md`](evidence/research/README.md)

Create validation, decision, architecture, or user docs only when there is a
specific durable owner and content for them.

## Editing Rules

- Update existing documents before creating new structure.
- Do not create placeholder directories, sentinel files, or broad scaffolds.
- Mark hypotheses, accepted decisions, and open questions explicitly when the
  distinction matters.
- Keep public-facing documentation under `docs/user/` when it is introduced,
  and treat it as redacted by default.
- Docs-only wording or navigation changes may not need tests. If there are no
  remaining executable tests for the changed area, say that explicitly.
