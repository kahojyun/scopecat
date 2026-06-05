# PR Documentation Drift Checklist

## Status

PR review checklist, not a release gate or architecture decision.

Use this checklist before opening or merging a PR that changes behavior,
fixtures, generated artifacts, tests, documentation contracts, or accepted
prototype boundaries. Keep it lightweight: the goal is to put facts in the
nearest owner and avoid turning candidates or future plans into current truth.

## Checklist

- **Terms**: use standard terms from
  [`terminology.md`](terminology.md). Distinguish workflow, capability,
  maturity, validation method, decision status, evidence, artifact boundary,
  and ownership.
- **Maturity**: classify maturity only for delivery objects named by the
  delivery maturity model: user journeys, workflows, use cases, vertical
  slices, and product capabilities. Treat candidates, spikes, prototypes,
  scenarios, and operations as evidence or validation methods, not maturity
  owners by themselves.
- **Owner**: update every affected owner, but keep each fact in one durable
  place: workflow and use case map for user journey, use case, scenario, operation,
  and validation status; target capability map for capability maturity;
  brownfield docs for current-state, transition-state, migration, and
  authority-transfer state; implementation register for live module ownership;
  prototype-boundary notes for route boundaries; module READMEs for API
  details; or discovery docs for evidence.
- **No duplicate state**: avoid copying the same current state, owner table,
  next work, or non-goal into multiple README files.
- **Candidate promotion**: if historical discovery results or retained
  candidate-shaped fixtures shaped the work, say whether they remain prior
  evidence or were promoted because they close a named use case, scenario,
  operation, workflow step, seam, or risk question.
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
- **Reader test**: a context-free reader should be able to answer which user
  journey, workflow, use case, implementation slice, or capability changed, what
  maturity changed, who owns it, and what remains unaccepted.
