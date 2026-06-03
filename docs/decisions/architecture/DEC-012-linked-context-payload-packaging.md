# DEC-012: Package Explicit Linked Context Payloads Without Importing Them

## Status

Decision type: architecture.

Decision status: accepted.

Date: 2026-06-03.

Owner: [`../../engineering/prototype-boundaries/handoff.md`](../../engineering/prototype-boundaries/handoff.md).

## Context

JNY-001 handoff packages already expose linked context as review-visible
references. That kept selected stored Measurement Record export narrow while
the package writer, opener, receiving gate, and import plan settled their basic
contracts.

The next package pressure is whether linked context can be present as package
payload when a caller explicitly declares one source file. This is useful for
reviewing a small context artifact alongside the selected measurement, but it
must not silently turn into recursive context capture, reference resolution, or
durable linked-context import.

## Decision

The route-local handoff package writer may package explicitly declared linked
context payload files when the caller supplies:

- a source-relative payload path;
- a package-relative destination under `context/`;
- expected SHA-256 digest and byte size;
- package state `packaged` and include status `included_by_user`.

The writer copies only that declared source file after digest and size
preflight. The package manifest records the linked payload's package path,
digest, and size. Package opening projects the linked context as
`packaged_payload`; integrity observation includes it as a declared package
member.

Package-writer ids remain caller-declared package-input facts. They do not
become durable Scopecat Measurement Record identity and do not replace
storage-backed selected-record export evidence.

Import planning and durable import do not import linked-context payloads.
DEC-016 keeps them as reviewable package contents, while import planning keeps
the action `keep_reference_only` with a `linked_context_payload_import`
non-claim.

Selected stored Measurement Record export remains a separate authority boundary.
DEC-014 narrows that path to request-declared record-local linked payloads
without treating recorded references as file-copy authority.

## Scope

This decision applies to:

- route-local handoff package writer inputs;
- DEC-010 directory manifest packages;
- package open and integrity observation for explicitly packaged linked
  context members;
- receiving gate and import planning non-claims for linked payload import.

This decision does not apply to:

- recursive relation traversal;
- reference resolution;
- environment, code, parameter-state, or prepared-run reconstruction;
- durable Measurement Records linked-context import;
- selected stored Measurement Record export linked-payload discovery;
- batch export/import package shape.

## Consequences

This gives the package writer a narrow linked-payload path and lets selected
stored-record export reuse it only through a later accepted authority boundary.
It also makes the import boundary explicit: packaged linked context can be
inspected and integrity-observed, but it does not become durable storage
content.

Future work must still decide how different context kinds are typed before any
durable import route can accept linked-context payloads.

## Alternatives Considered

- Option: keep all linked context reference-only. Rejected for the generic
  writer because the package/integrity stack already has a safe package-member
  model for explicitly declared files.
- Option: import packaged linked payloads durably now. Rejected because durable
  Measurement Records import does not yet own linked-context storage semantics.
- Option: recursively capture linked references. Rejected because this slice
  only validates caller-declared package members and avoids broad context
  traversal.

## Supersession

Supersedes:

- none.

Superseded by:

- none.

## Review Triggers

Revisit this decision when:

- selected stored Measurement Record export needs broader linked-payload discovery;
- durable import needs to store linked-context payloads under a context artifact contract;
- context kind schemas become product contracts;
- batch export/import needs package-level context topology;
- GUI review needs richer packaged-context presentation.

## Related Evidence And Owners

- [`DEC-010-package-format-directory-manifest.md`](DEC-010-package-format-directory-manifest.md)
- [`DEC-016-defer-linked-context-payload-import.md`](DEC-016-defer-linked-context-payload-import.md)
- [`../../engineering/prototype-boundaries/handoff.md`](../../engineering/prototype-boundaries/handoff.md)
- [`../../engineering/workflow-validation-map.md`](../../engineering/workflow-validation-map.md)
- [`../../../tests/prototypes/handoff/test_handoff_engineering_prototype_writer.py`](../../../tests/prototypes/handoff/test_handoff_engineering_prototype_writer.py)
