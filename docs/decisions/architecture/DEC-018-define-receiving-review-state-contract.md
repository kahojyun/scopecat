# DEC-018: Define Receiving Review State Without Persisted GUI State

## Status

Decision type: architecture.

Decision status: accepted.

Date: 2026-06-03.

Owner: [`../../engineering/prototype-boundaries/handoff.md`](../../engineering/prototype-boundaries/handoff.md).

## Context

JNY-001 receiving now has a complete backend review chain:

- open a directory-manifest handoff package read-only;
- observe declared package-member integrity;
- run an approved receiving gate;
- build a non-mutating import plan;
- optionally write a local static inspection artifact;
- adapt exactly one ready planned measurement into durable Measurement Records
  import.

These steps return local receipts, but there is no live GUI route and no
cross-session GUI review store. This decision resolves whether GUI receiving
state should become a durable model now, or whether the current backend
receipts should remain the source for any future UI projection.

## Decision

Define receiving review state as a derived local projection over existing
handoff package, integrity, receiving-gate, import-plan, inspection, and
durable-import receipt facts. Do not add a persisted GUI-owned receiving state
store in the current JNY-001 slice.

A future GUI receiving surface should be able to project, at minimum:

- package identity and opened package path;
- preview classification and measurement ids;
- integrity classification, member count, and integrity findings;
- receiving-gate approval and whether acceptance is allowed;
- selected measurement ids and import-plan freshness relative to the opened
  package and integrity observation;
- per-measurement import-plan readiness and blocked reasons;
- linked-context review handling, including DEC-016 `keep_reference_only`;
- durable-import result or retry summary for one selected measurement;
- explicit non-claims for external authenticity/trust, archive extraction, batch
  durable import, linked-context payload import, and storage mutation before
  durable import.

The state projection is local review state. It is not a portable package
artifact, package acceptance, durable storage mutation authority, external
trust evidence, or GUI-owned state store. DEC-023 later accepts a narrow local
receipt materialization boundary for cross-session review continuity.

## Scope

This decision applies to:

- receiving-side local review projections;
- package open, integrity observation, receiving gate, import plan, optional
  inspection receipt, durable-import receipt, and retry summary composition;
- future GUI-facing view-model requirements for JNY-001 receiving.

This decision does not apply to:

- implementing a frontend;
- persistent GUI storage;
- collaborative review state;
- external authenticity or trust policy;
- archive extraction;
- batch durable import beyond DEC-017;
- linked-context payload import beyond DEC-016.

## Consequences

The backend does not need a new persistence layer before a GUI exists. The
current route-local receipts remain authoritative local review surfaces, and a
future GUI can compose them into a review-state projection without changing
package or durable-import contracts.

The current implementation exposes that composition as
`project_handoff_receiving_review_state()`. The projection accepts typed local
receiving-gate, import-plan, durable-import summary, retry-review, and error
diagnostic evidence; validates package continuity across supplied receipts; and
returns a `local_receiving_review_state_projection` summary with explicit
non-claims. It remains a read-only local review surface, not a persisted GUI
store.

Future GUI work must still decide where GUI-owned review state lives, how
freshness is checked across sessions, how user acknowledgement is recorded, and
whether GUI state should become durable or remain a derived view over receipts.
DEC-023 local receipts do not answer those GUI ownership questions.

## Alternatives Considered

- Option: add a persistent GUI receiving store now. Rejected because there is no
  live GUI owner or cross-session workflow to validate persistence semantics.
- Option: keep GUI state entirely unspecified. Rejected because receiving UI
  work needs a stable list of backend facts it can project without implying
  mutation authority.
- Option: treat the import plan as GUI state. Rejected because the import plan
  is only one part of receiving review and is explicitly non-mutating.

## Supersession

Supersedes:

- none.

Superseded by:

- none.

## Review Triggers

Revisit this decision when:

- a live GUI route needs to persist receiving review state across sessions;
- DEC-023 local receipts need to become GUI-owned state;
- users need to resume package review after package bytes or integrity facts
  change;
- import retry review needs GUI-owned acknowledgement;
- a separately accepted authenticity/trust policy adds package review states;
- archive extraction adds package materialization state before opening.

## Related Evidence And Owners

- [`DEC-010-package-format-directory-manifest.md`](DEC-010-package-format-directory-manifest.md)
- [`DEC-011-package-trust-authenticity-posture.md`](DEC-011-package-trust-authenticity-posture.md)
- [`DEC-013-batch-receiving-import-planning.md`](DEC-013-batch-receiving-import-planning.md)
- [`DEC-016-defer-linked-context-payload-import.md`](DEC-016-defer-linked-context-payload-import.md)
- [`DEC-017-defer-batch-durable-import.md`](DEC-017-defer-batch-durable-import.md)
- [`DEC-020-defer-archive-package-implementation.md`](DEC-020-defer-archive-package-implementation.md)
- [`DEC-023-accept-local-receiving-review-state-receipts.md`](DEC-023-accept-local-receiving-review-state-receipts.md)
- [`../../engineering/prototype-boundaries/handoff.md`](../../engineering/prototype-boundaries/handoff.md)
- [`../../engineering/prototype-boundaries/handoff-durable-import-storage.md`](../../engineering/prototype-boundaries/handoff-durable-import-storage.md)
- [`../../engineering/workflow-validation-map.md`](../../engineering/workflow-validation-map.md)
- [`../../../src/scopecat/handoff/receiving.py`](../../../src/scopecat/handoff/receiving.py)
- [`../../../src/scopecat/handoff/import_plan.py`](../../../src/scopecat/handoff/import_plan.py)
- [`../../../src/scopecat/handoff/review_state.py`](../../../src/scopecat/handoff/review_state.py)
