# DEC-016: Defer Linked Context Payload Import

## Status

Decision type: architecture.

Decision status: accepted.

Date: 2026-06-03.

Owner: [`../../engineering/prototype-boundaries/handoff-durable-import-storage.md`](../../engineering/prototype-boundaries/handoff-durable-import-storage.md).

## Context

DEC-012 allows explicitly declared linked-context payload files to be packaged
under `context/`. DEC-014 extends that package-member path to selected stored
Measurement Record export when the export request declares record-local source
bytes. Package opening and integrity observation can therefore review linked
payloads as package contents.

Durable import is a different boundary. The current handoff durable-import
adapter creates exactly one new Measurement Record by adapting one planned
package measurement into the Measurement Records durable import pipeline. That
pipeline currently owns primary-data import only. Linked context has no
accepted durable storage contract for destination paths, context kind schemas,
attachment semantics, conflicts, retry behavior, or read-model projection.

## Decision

Do not import linked-context payloads into durable Measurement Records storage
in the current JNY-001 handoff slice.

Packaged linked-context payloads remain reviewable handoff package contents.
Receiving/import planning may list them and preserve managed context-reference
metadata, but the action remains `keep_reference_only` and the durable-import
adapter must keep the `linked_context_payload_import` non-claim.

Any future linked-context payload import must be promoted through a separate
decision and implementation slice that defines, at minimum:

- accepted context kinds or a generic context artifact contract;
- destination topology in Measurement Records storage;
- attachment semantics to one or more Measurement Records;
- digest, byte-size, and package-integrity preflight rules;
- no-overwrite, conflict, rollback, and retry behavior;
- read-model projection and local review receipt shape.

## Scope

This decision applies to:

- DEC-010 directory manifest packages;
- DEC-012 linked-context package members;
- DEC-014 selected-record linked-context payload export;
- receiving gate and import-plan output;
- handoff durable-import adaptation to Measurement Records storage.

This decision does not apply to:

- package writing or package integrity observation;
- read-only package inspection;
- future context-kind schema design;
- durable context artifact storage after a later accepted decision;
- recursive linked-reference traversal.

## Consequences

This preserves a clear split between portable package review and durable
storage mutation. Users can package and inspect declared context payloads, but
importing a package measurement will not silently create context artifacts or
attach arbitrary files to a durable record.

The remaining handoff extension pressure shifts to archive
packaging/extraction, signed package policy beyond DEC-019, or a future
explicitly scoped context-artifact import contract. GUI receiving state
projection is governed by DEC-018.

## Alternatives Considered

- Option: import linked payloads as loose files beside the durable record.
  Rejected because destination topology, conflict behavior, and read-model
  projection would be implicit.
- Option: attach all packaged linked payloads to the imported Measurement
  Record. Rejected because linked context can target multiple package
  measurements and has no accepted attachment semantics.
- Option: import only known context kinds now. Rejected because no accepted
  context-kind schema exists for durable handoff import.

## Supersession

Supersedes:

- none.

Superseded by:

- none.

## Review Triggers

Revisit this decision when:

- Measurement Records gains a durable context artifact contract;
- a named workflow requires importing parameter-state, code, environment, or
  other context payloads;
- receiving review needs explicit context-payload destination assignment;
- retry review needs to coordinate primary-data and context-payload import;
- GUI review needs persistent context-import selection state.

## Related Evidence And Owners

- [`DEC-012-linked-context-payload-packaging.md`](DEC-012-linked-context-payload-packaging.md)
- [`DEC-014-selected-record-linked-context-payload-export.md`](DEC-014-selected-record-linked-context-payload-export.md)
- [`DEC-018-define-receiving-review-state-contract.md`](DEC-018-define-receiving-review-state-contract.md)
- [`../../engineering/prototype-boundaries/handoff.md`](../../engineering/prototype-boundaries/handoff.md)
- [`../../engineering/prototype-boundaries/handoff-durable-import-storage.md`](../../engineering/prototype-boundaries/handoff-durable-import-storage.md)
- [`../../engineering/workflow-validation-map.md`](../../engineering/workflow-validation-map.md)
- [`../../../src/scopecat/handoff/import_plan.py`](../../../src/scopecat/handoff/import_plan.py)
- [`../../../src/scopecat/handoff/durable_import.py`](../../../src/scopecat/handoff/durable_import.py)
