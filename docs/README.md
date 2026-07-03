# Scopecat Target Design Documents

The documents in this directory define Scopecat's target design. They are not
an implementation inventory and should not be read as a promise that the
current code already has every model or API described here.

Other repository READMEs may describe the current package, examples, or local
developer workflow. `docs/` is different: it records durable direction,
architecture constraints, and boundaries that future code should converge on.

## Document Set

- [Project charter](project-charter.md): product scope, users, non-goals, and
  design principles.
- [Architecture](architecture.md): target experiment stack, core records,
  ownership boundaries, point identity, record contracts, and runtime split.
- [Experiment workflow](experiment-workflow.md): target user workflow from
  authoring through run execution, capture, data, analysis, candidates, and
  adaptive continuation.
- [Parameter system](parameter-system.md): accepted configuration state,
  deterministic views, run-time overrides, candidates, and validation policy.
- [Data and storage contracts](data-storage-contracts.md): durable record graph,
  content-addressed refs, result contracts, shape policy, artifacts,
  provenance, and diagnostics.
- [Extension boundaries](extension-boundaries.md): core/domain split, quantum
  deferral, instrument boundaries, legacy capture, and GUI/workbench rules.

## Admission Rule

Add or update a document only when it answers at least one of these questions:

- What target behavior or non-goal should future changes preserve?
- Which durable record, identity rule, or boundary would be hard to infer from
  code alone?
- Which ownership rule prevents domain, storage, GUI, hardware, or legacy
  adapter concerns from leaking into the core?
- Which explicit deferral prevents premature abstraction?

Do not use `docs/` for migration logs, module inventories, field-by-field
mirrors of current code, short-term task lists, or compatibility notes.
