# Scopecat Design Documents

This directory is deliberately small. Keep documents here only when they define
project direction, durable architecture, or constraints that would be costly to
recover from code and tests.

Do not use `docs/` to mirror the current implementation. Module lists, field
inventories, migration logs, and short-term plans belong in code, tests,
fixtures, issues, or commit history.

## Long-Lived Documents

- [Project charter](project-charter.md): product scope, users, non-goals, and
  architecture principles.
- [Architecture](architecture.md): accepted core model, package boundaries,
  experiment kernel, relation rules, and ownership split.
- [Experiment workflow](experiment-workflow.md): stable public workflow from
  workspace opening through runs, data, analysis, candidates, comparison, and
  structured overviews.
- [Parameter system](parameter-system.md): accepted parameter-state,
  derivation, patch, and candidate resolution model.
- [Data and storage contracts](data-storage-contracts.md): durable record
  graph, artifact indexing, measurement shapes, plan previews, calibration
  evidence, and diagnostics constraints.
- [Extension boundaries](extension-boundaries.md): core/domain split, example
  package rules, future domain extraction criteria, and GUI/workbench entry
  constraints.

## Admission Rule

Add a new document only when it answers at least one of these questions:

- What direction or non-goal should future changes preserve?
- Which durable record or boundary would be hard to infer from code alone?
- Which ownership rule prevents domain, storage, GUI, or adapter concerns from
  leaking into the core?
- Which explicit deferral prevents premature abstraction?

Otherwise, update the relevant code, tests, fixtures, or one of the existing
documents.
