# PR Documentation Drift Checklist

## Status

PR review checklist, not a release gate or architecture decision.

Use this checklist before opening or merging a PR that changes behavior,
fixtures, generated artifacts, tests, documentation contracts, or accepted
prototype boundaries. Keep it lightweight: the goal is to put facts in the
nearest owner and avoid turning candidates or future plans into current truth.

## Checklist

- **Phase**: classify the change as discovery evidence, implementation
  candidate, engineering prototype, production vertical slice, or supported
  workflow.
- **Owner**: update the nearest owner only: workflow map for workflow status,
  slice register for live implementation ownership, prototype-boundary notes
  for route boundaries, module READMEs for API details, or discovery docs for
  evidence.
- **No duplicate state**: avoid copying the same current state, owner table,
  next work, or non-goal into multiple README files.
- **Candidate promotion**: if discovery results or `implementation_candidates/`
  shaped the work, say whether they remain evidence or were promoted because
  they close a named workflow step, seam, or risk question.
- **Artifact boundary**: classify new or changed fixtures, expected outputs,
  receipts, review artifacts, packages, or exports as repository-safe fixture,
  local/review surface, or portable/export artifact.
- **Docs with code**: when behavior, API, artifact shape, fixture, or expected
  output changes, update the owning module README, prototype-boundary note,
  tests, fixtures, and expected outputs together.
- **Archive discipline**: do not update archive or history docs to mirror
  current APIs. Edit them only for broken links, safety issues, or explicit
  supersession clarification.
- **Future flexibility**: do not describe an unvalidated future owner, request
  shape, schema, GUI, storage model, SDK, or redaction policy as accepted.
- **Reader test**: a context-free reader should be able to answer what phase
  changed, who owns it, and what was not accepted.
