# DEC-023: Accept Local Receiving Review State Receipts

## Status

Decision type: architecture.

Decision status: accepted.

Date: 2026-06-04.

Owner: [`../../engineering/prototype-boundaries/handoff.md`](../../engineering/prototype-boundaries/handoff.md).

## Context

DEC-018 defines receiving review state as a derived local projection over
package-open, integrity, receiving-gate, import-plan, durable-import,
retry-review, and error diagnostic evidence. It intentionally rejected a
persisted GUI-owned receiving state store because no live GUI route owned
cross-session state semantics.

JNY-001 now needs a narrower continuity mechanism: a receiver should be able to
materialize the current local review projection as an auditable local receipt
without turning that receipt into package acceptance, storage mutation
authority, a GUI-owned state database, or a public view-model schema.

## Decision

Accept local receiving review state receipts for workflow continuity. A receipt
may persist the current `local_receiving_review_state_projection` summary as a
no-overwrite local JSON receipt under caller-provided local state storage.

The receipt is local review evidence only. It records the projection summary,
request id, receipt path, package id, and classification. It does not replace
package-open, integrity, receiving-gate, import-plan, durable-import,
retry-review, or error diagnostic receipts as the source facts.

DEC-018 remains in force for the projection contract. This decision narrows the
persistence boundary to receipt materialization only; it does not accept a
GUI-owned state store.

## Scope

This decision applies to:

- JNY-001 receiving review workflow continuity;
- local no-overwrite JSON receipts derived from
  `local_receiving_review_state_projection`;
- route-local compatibility and prototype tests for the receipt artifact
  posture.

This decision does not apply to:

- implementing a frontend;
- GUI-owned state storage;
- collaborative review state;
- package acceptance or durable import authority;
- retry authorization;
- package mutation or storage mutation;
- portable/export package artifacts;
- public SDK or public view-model schema.

## Consequences

Users and local tools can save the current receiving review state for
cross-session continuity without changing package or durable-import authority.
The receipt can be re-read by local tooling later, but a caller must still use
fresh package and receipt evidence when an operation requires continuity or
mutation authority.

The implementation exposes
`write_handoff_receiving_review_state_receipt()` as a local no-overwrite
receipt writer. It materializes the existing projection summary and keeps
storage mutation, package mutation, GUI state store, portable export, retry
authorization, and public view-model schema unclaimed.

## Alternatives Considered

- Option: keep receiving review state projection only. Rejected because it does
  not give local tools a stable receipt for resume-oriented review continuity.
- Option: add a GUI-owned state store now. Rejected because the current slice
  still has no frontend route, collaborative state model, or GUI persistence
  semantics.
- Option: treat the persisted receipt as acceptance authority. Rejected because
  acceptance and durable import must still rely on explicit receiving/import
  approvals and source receipts.

## Supersession

Supersedes:

- none.

Superseded by:

- none.

## Review Triggers

Revisit this decision when:

- a live GUI route needs to own persisted receiving state;
- local receipt replay needs to reconstruct typed receipt objects instead of
  storing review summaries;
- collaborative review state or multi-user acknowledgement is required;
- package bytes, integrity facts, or import-plan freshness need automated
  cross-session invalidation;
- public SDK or GUI view-model schemas need publication.

## Related Evidence And Owners

- [`DEC-018-define-receiving-review-state-contract.md`](DEC-018-define-receiving-review-state-contract.md)
- [`DEC-021-accept-safe-archive-materialization.md`](DEC-021-accept-safe-archive-materialization.md)
- [`../../engineering/prototype-boundaries/handoff.md`](../../engineering/prototype-boundaries/handoff.md)
- [`../../engineering/workflow-validation-map.md`](../../engineering/workflow-validation-map.md)
- [`../../../src/scopecat/handoff/review_state.py`](../../../src/scopecat/handoff/review_state.py)
