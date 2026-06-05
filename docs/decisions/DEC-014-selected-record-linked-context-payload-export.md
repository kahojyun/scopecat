# DEC-014: Allow Selected-Record Linked Context Payload Export

## Status

Decision type: architecture.

Decision status: accepted.

Date: 2026-06-03.

## Context

DEC-012 lets the route-local package writer copy explicitly declared
linked-context payload files under `context/` while keeping import
reference-only. The selected stored Measurement Record export path still needed
its own authority boundary because stored records may contain references that
are not enough to authorize payload packaging.

The selected-record export path is the JNY-001 storage-backed product-slice
candidate. It must preserve durable Measurement Record evidence while avoiding
implicit reference traversal, context discovery, or broad file capture.

## Decision

Selected stored Measurement Record export may package a linked-context payload
only when the selected export request explicitly declares:

- a `source_path` that stays under the selected record's `record_dir`;
- a package destination under `context/`;
- an expected SHA-256 digest;
- an expected byte size.

The selected export adapter validates that declared source path against the
selected record directory, then delegates copying, digest/size preflight,
manifest writing, package opening, and integrity observation to the handoff
package writer and reader.

Stored Measurement Record linked references remain review references. They are
not payload authority by themselves, and selected export does not recursively
resolve references or discover eligible context files from record metadata.

Import planning and durable import continue to exclude linked-context payload
import under DEC-016. Packaged linked context is reviewable package content
only.

## Scope

This decision applies to:

- selected stored Measurement Record export requests;
- record-local linked-context payload source validation;
- DEC-010 directory manifest packages;
- DEC-012 linked-context package-member writing, opening, and integrity
  observation.

This decision does not apply to:

- recursive linked-reference traversal;
- treating recorded references as payload authority;
- durable linked-context import;
- selected-record batch export topology;
- context-kind schemas or shared domain schemas;
- GUI review state.

## Consequences

The JNY-001 selected-record export path can now include small declared context
payloads without weakening the storage-backed identity and continuity checks.
The authority remains explicit: the export request names the record-local file
and expected bytes, while the package writer owns package-member validation.

Future work must still decide whether selected-record batch export needs richer
package-level context topology and whether context kinds need stable schemas.

## Alternatives Considered

- Option: keep selected stored-record export reference-only. Rejected because
  DEC-012 already proved a safe package-member path when the source is
  explicitly declared and digest-checked.
- Option: package any recorded linked reference automatically. Rejected because
  references are review facts, not file-copy authority.
- Option: allow linked payloads outside the selected record directory. Rejected
  because that would turn selected-record export into broader workspace file
  capture.

## Supersession

Supersedes:

- none.

Superseded by:

- none.

## Review Triggers

Revisit this decision when:

- durable import needs to store linked-context payloads under a context artifact contract;
- selected stored Measurement Record batch export needs shared context
  topology;
- context kind schemas become product contracts;
- recorded references gain a separate accepted payload-authority model;
- GUI review needs persistent linked-context selection state.

## Related Evidence

- [`DEC-010-package-format-directory-manifest.md`](DEC-010-package-format-directory-manifest.md)
- [`DEC-012-linked-context-payload-packaging.md`](DEC-012-linked-context-payload-packaging.md)
- [`DEC-016-defer-linked-context-payload-import.md`](DEC-016-defer-linked-context-payload-import.md)
- [`../../engineering/prototype-boundaries/handoff.md`](../engineering/prototype-boundaries/handoff.md)
- [`../../engineering/workflow-validation-map.md`](../engineering/workflow-validation-map.md)
- [`../../../tests/prototypes/handoff/test_handoff_selected_record_export.py`](../../tests/prototypes/handoff/test_handoff_selected_record_export.py)
