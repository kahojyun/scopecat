# Scopecat Docs

`docs/` is Scopecat's long-lived project memory. It preserves context that
must survive across AI sessions and the project lifecycle: product framing,
research conclusions, problem framing, architecture contracts,
decisions, public user documentation, and unresolved questions.

Do not use `docs/` for temporary reasoning, per-session task lists, or notes
that can be handled inside one AI session.

## Entry Points

- `index.md` lists the current high-value documents and how to use
  them.
- `strategy/product-brief.md` states current product direction and boundaries:
  what Scopecat does, how it complements existing experiment systems, what
  complexity belongs to users or lab-owned adapters, and what is not a default
  adoption requirement.
- `discovery/adoption-hypotheses.md` owns provisional product-value
  hypotheses; the tracker only coordinates their current phase.
- `evidence/inventory.md` owns stable evidence claims, while
  `evidence/method.md` owns interpretation rules.
- `discovery/problem-briefs/README.md` indexes evidence-backed problem briefs
  without promoting them into validation artifacts or product scope.
- `AGENTS.md` contains rules that should apply to every AI session working
  inside `docs/`.

Use `index.md` for the fuller inventory. This README should stay an
entry point, not a second index.

## Analysis Model

Use this ownership model for product analysis:

```text
Source material
  -> Evidence and claim hygiene
  -> Problem and workflow framing
  -> Hypotheses and validation questions
  -> Validation result or deletion
  -> Product decision or contract only when needed
```

Adjacent steps can be worked in the same pass, but they should not collapse
into the same artifact by default. Evidence hygiene, problem framing, option
exploration, validation results, and product contracts have different owners.

The current project is mostly in evidence hygiene, problem framing, and
hypothesis comparison. Validation, decision, contract, and ADR documents should
appear only when they answer a concrete next question.

Progressive adoption stories should be product-value-first: users adopt a
useful path, not a subsystem name. Historical capability names may preserve
design pressure, but they should not become default document structure,
implementation ownership, or a ranked backlog.

## Validation

For changes that affect executable behavior, reference-case contracts, expected
outputs, or validation claims, run the relevant focused command when one
exists.

Docs-only wording or navigation changes may not need tests. If there are no
remaining executable tests for the changed area, say that explicitly.

## Editing Rules

- Create the narrowest durable document with a real owner and purpose.
- Update existing documents before creating new structure.
- Do not create placeholder directories, sentinel files, or broad scaffolds.
- Mark hypotheses, accepted decisions, and open questions explicitly when the
  distinction matters.
- Keep public-facing documentation under `docs/user/` when it is introduced,
  and treat it as redacted by default.
