# Scopecat Docs

`docs/` is Scopecat's long-lived project memory. It preserves context that
must survive across AI sessions and the project lifecycle: product framing,
journeys, research conclusions, architecture contracts, decisions, public user
documentation, and unresolved questions.

Do not use `docs/` for temporary reasoning, per-session task lists, or notes
that can be handled inside one AI session.

## Entry Points

- `document-index.md` lists the current high-value documents and how to use
  them.
- `vision.md` states current project-level product direction and boundaries:
  what Scopecat does, what is not a default adoption requirement, and how it
  should complement existing experiment systems.
- `jc-analysis-operating-standard.md` defines repeatable `JC-###` status,
  source-map, promotion, acceptance, conflict, and reopening workflow.
- `AGENTS.md` contains rules that should apply to every AI session working
  inside `docs/`.

Use `document-index.md` for the fuller inventory. This README should stay an
entry point, not a second index.

## Analysis Model

Use this promotion path for durable product and architecture work:

```text
Evidence -> User Journey -> Pain Point -> Product Capability
  -> Domain Concept -> Architecture Contract -> Subsystem Spec
```

Research and product discovery should be journey-first. Progressive adoption
stories should be capability-first. Subsystem or capability docs should define
ownership and contracts, not duplicate the whole product discovery process.

## Editing Rules

- Create the narrowest durable document with a real owner and purpose.
- Update existing documents before creating new structure.
- Do not create placeholder directories, sentinel files, or broad scaffolds.
- Mark hypotheses, accepted decisions, and open questions explicitly when the
  distinction matters.
- Keep public-facing documentation under `docs/user/` when it is introduced,
  and treat it as redacted by default.
