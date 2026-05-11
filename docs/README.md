# Scopecat Documentation

## Purpose

`docs/` is the long-lived project memory for Scopecat. It should preserve
context that must survive across AI sessions and across the project lifecycle:
product framing, user journeys, durable research conclusions, architecture
contracts, decisions, public user documentation, and unresolved questions.

It is not a scratchpad for temporary reasoning, per-session task lists, or
notes that can be handled inside one AI session.

## Current State

The project is still in an early greenfield design phase. Avoid creating a
large directory scaffold before the documents have real durable content.

Current durable documents:

```text
docs/
  AGENTS.md
  README.md
  progressive-adoption-progress-tracker.md
  research/
    README.md
    greenfield-experimental-automation-architecture-notes.md
```

## Documentation Model

Use this model when deciding where new long-lived docs belong:

```text
Evidence -> User Journey -> Pain Point -> Product Capability
  -> Domain Concept -> Architecture Contract -> Subsystem Spec
```

The key split is:

- research and product discovery should be journey-first;
- progressive adoption stories should be capability-first;
- subsystem or capability docs should describe ownership and contracts, not
  duplicate the whole product discovery process;
- public user docs should be separated from internal project docs when they
  are introduced.

## Future Areas

Create these areas only when there is durable content for them:

```text
docs/
  user/          # Public, redacted MkDocs-facing documentation.
  project/       # Vision, glossary, roadmap, and project context.
  product/       # Personas, evidence, pain points, opportunity maps.
  journeys/      # End-to-end user journeys that cross capabilities.
  architecture/  # System map, ownership, dependencies, contracts.
  capabilities/  # Capability-level adoption, domain, and architecture notes.
  concepts/      # Stable cross-capability domain concept cards.
  decisions/     # Project-wide ADRs.
  research/      # Raw or semi-processed research inputs.
```

Do not create sentinel directories or placeholder files just to reserve names.

## User Documentation

Future user-facing docs should live under `docs/user/` and be treated as
publishable by default. Anything under `docs/user/` needs public-docs redaction
review before publication.

Internal project, product, architecture, research, and AI-assistive docs should
not be mixed into the public MkDocs navigation unless intentionally promoted.

## AI Guidance

Rules that should apply on every AI session inside `docs/` belong in
`docs/AGENTS.md`.

Longer background that is only sometimes needed can become normal docs when
there is durable content for it. Do not create an `ai/` directory for session
logs or transient handoffs.

## Editing Rules

- Create the narrowest durable document that has a real owner and purpose.
- Keep early documents explicit about hypotheses, accepted decisions, and open
  questions.
- Prefer one owning document per durable fact; cross-links should reference,
  not duplicate.
- Update existing documents before creating new structure.
- Keep public-facing material redacted by default.
