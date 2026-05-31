# Parameter Compatibility Artifacts Boundary Clarification

## Status

Boundary documentation validated, not an ADR.

This document clarifies the current discovery posture after the prepared-run
parameter-state review, operator approval, and compatibility-adapter evidence
slices.

## Clarified Boundary

The managed parameter-state snapshot is the canonical Scopecat run context for
parameters.

Generated compatibility files, compatibility objects, adapter requests, adapter
receipts, stdout/stderr, and adapter diagnostics are derivative operational
artifacts. They are not primary parameter context, not parameter state, and not
required for measurement validity by default.

Scopecat should not require users to model compatibility artifacts when they
already select and review a managed parameter-state snapshot. User-owned run
scripts may generate whatever legacy JSON, Python object, control-stack input,
or downstream artifact they need from the selected snapshot without Scopecat
owning that derivative artifact.

## Active Route Posture

The recommended core route is:

- select a managed parameter-state snapshot as run context;
- review and acknowledge any scope findings;
- record an operator decision if needed;
- let user code or lab adapters derive operational objects outside core
  Scopecat context.

The parameter-state snapshot remains the stable identity to compare, rerun,
review, and attach to measurement records. Compatibility outputs should not
become a second authority for parameter values.

## Compatibility Evidence Posture

The following validated slices remain useful as exploratory evidence only:

- [`parameter-write-compatibility-output-validation-result.md`](parameter-write-compatibility-output-validation-result.md)
- [`approved-parameter-compatibility-adapter-request-validation-result.md`](approved-parameter-compatibility-adapter-request-validation-result.md)
- [`adapter-authored-parameter-compatibility-output-preview-validation-result.md`](adapter-authored-parameter-compatibility-output-preview-validation-result.md)

They prove possible boundaries for derivative compatibility artifacts when a
user explicitly wants review/debug evidence. They do not establish a required
Scopecat workflow, public adapter API, compatibility-output subsystem, or
measurement-context family.

## When To Record Compatibility Artifacts

Record compatibility artifacts only when the user explicitly supplies them as
debug, audit, or handoff evidence.

Acceptable future posture:

- generic debug/attachment artifact references;
- optional adapter diagnostic summaries;
- reference-only links back to the selected parameter-state snapshot and
  operator decision;
- no payload import unless a separate artifact route earns it;
- no external file authority claim unless a separate storage/import route earns
  it.

Do not treat generated compatibility files as normal run context merely because
they were produced during preparation. If they affected a run, the stable
Scopecat context should still be the selected parameter-state snapshot, with
the derivative artifact recorded only as supporting debug evidence when useful.

## Not Earned

This clarification does not earn:

- compatibility-output ownership in Scopecat core;
- adapter execution;
- stable public adapter API;
- external compatibility file authority;
- required measurement context links for compatibility output;
- hardware control or parameter write-back;
- file observation or durable artifact storage;
- GUI workflow.

## Reopen Triggers

Reopen compatibility-output modeling only if real workflow pressure shows one
of these needs:

- users must audit generated legacy artifacts independently of the managed
  parameter snapshot;
- external collaborators require a reviewed derivative artifact receipt;
- adapters need a stable interchange contract because multiple labs or tools
  implement the same handoff;
- debug attachments become frequent enough to warrant a generic artifact route.

Until then, prefer the simpler rule: parameter state is context; derivative
compatibility artifacts are optional debug/attachment evidence.
