# Scopecat Design Notes

The documents in this directory record the current direction of Scopecat. They
are working notes for a single-developer, local-first project, not a stability
promise for internal records, schemas, APIs, or file layouts.

Scopecat is in a fast redesign phase. When a cleaner model wins, update the
code, tests, fixtures, and docs in the same pass instead of preserving
compatibility layers for abandoned internal shapes.

## Document Set

- [Project charter](project-charter.md): long-term product direction,
  non-goals, and design principles.
- [Problems, failures, outcomes, events, and logs](problem-error-outcome.md):
  reporting-channel boundaries and failure semantics.
- [Layered transient IR architecture](ir-architecture.md): IR layers,
  dependency rules, semantic invariants, extension boundaries, and migration
  direction.
- [Module layout and dependency direction](module-layout.md): package
  responsibilities, composition boundaries, and executable layering rules.
- [Quantum domain package architecture](quantum-domain-architecture.md):
  hardware-independent quantum semantics and the laboratory target boundary.

## Admission Rule

Add or update a document only when it clarifies one of these:

- a long-term direction that should survive implementation churn;
- a non-goal that prevents premature platform, GUI, storage, hardware, or
  domain-specific expansion;
- a temporary design decision that would be hard to recover from code alone.

Do not use `docs/` for internal contract catalogs, compatibility notes, schema
mirrors, migration logs, field-by-field inventories, or short-term task lists.
