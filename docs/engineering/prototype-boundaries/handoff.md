# Handoff Package Boundary

## Status

Accepted engineering-prototype boundary.

## Purpose

Own the current package-use boundary for `scopecat.handoff`: package writing,
selected stored-record package export, read-only package open, receiving gate,
and non-mutating import planning.

Durable Measurement Records mutation is not owned by this file. It is covered
by [`handoff-durable-import-storage.md`](handoff-durable-import-storage.md).
Live package-root API orientation lives in
[`../../../src/scopecat/handoff/README.md`](../../../src/scopecat/handoff/README.md).

## Boundary

The package-use flow is:

```text
caller-declared or selected-record source facts
  -> package writer request
  -> ADR-0006 directory package
  -> read-only package open
  -> receiving gate
  -> non-mutating import plan
```

The package writer may package caller-declared normalized primary CSV data and
explicit linked-context payloads. Caller-declared package ids, measurement ids,
and linked-context ids are reviewed package-input facts, not durable
Measurement Record identity.

Selected stored-record export selects records by `record_id` and consumes the
Measurement Records-owned packageable handoff projection. Handoff delegates
record lookup, read-model freshness, record/receipt continuity checks, and
exportability classification to Measurement Records. Handoff does not parse
record-local Measurement Records artifacts, mutate Measurement Records storage,
or own read-model refresh.

Read-only package use validates the package manifest, opens package-local
primary CSV data for preview-ready measurements, observes declared integrity,
and projects review facts for receiving. Import planning remains non-mutating:
it records package-local facts for later review but accepts no destination
storage authority.

Selected stored-record batch export may write one multi-measurement package.
Batch receiving/import planning may review multiple measurements. Durable
handoff import remains one planned measurement per storage mutation under the
separate durable-import boundary.

## Artifact Authority

The package directory and `package-manifest.json` are portable handoff
artifacts. Package contents must use package-relative paths and validated
managed references at the package/export boundary.

Local writer receipts, workflow receipts, receiving-gate results,
selected-export receipts, and import-plan objects are local review surfaces
unless a later accepted boundary promotes one as portable/export output.

Declared digest integrity may gate local review and import planning. External
authenticity, sender trust, package provenance, and scientific validity remain
unclaimed.

## Related Decisions

| Decision | Governs |
| --- | --- |
| [`ADR-0006`](../../adr/ADR-0006-package-format-directory-manifest.md) | Directory manifest package format. |
| [`ADR-0007`](../../adr/ADR-0007-package-trust-authenticity-posture.md) | Declared-integrity posture and trust non-claims. |
| [`ADR-0008`](../../adr/ADR-0008-linked-context-payload-packaging.md) | Generic package-writer linked-context payload packaging. |
| [`ADR-0009`](../../adr/ADR-0009-batch-receiving-import-planning.md) | Multi-measurement receiving/import planning without batch durable import. |
| [`ADR-0010`](../../adr/ADR-0010-selected-record-linked-context-payload-export.md) | Selected-record linked-context payload export. |
| [`ADR-0011`](../../adr/ADR-0011-selected-record-batch-package-export.md) | Selected-record batch package export. |
| [`ADR-0012`](../../adr/ADR-0012-defer-linked-context-payload-import.md) | Linked-context payload import deferral. |
| [`ADR-0013`](../../adr/ADR-0013-defer-batch-durable-import.md) | Batch durable import deferral. |
| [`ADR-0014`](../../adr/ADR-0014-defer-archive-authority-and-archive-backed-durable-import.md) | Archive authority and archive-backed durable import deferral. |
| [`ADR-0015`](../../adr/ADR-0015-accept-safe-archive-materialization.md) | Safe archive materialization. |
| [`ADR-0016`](../../adr/ADR-0016-accept-safe-archive-creation.md) | Safe archive creation. |
| [`ADR-0017`](../../adr/ADR-0017-defer-existing-record-update-and-final-storage-schema.md) | Source-storage-read-only export and new-record-only durable import. |

## Out Of Scope

This boundary does not accept:

- durable Measurement Records mutation;
- final public SDK names or package publishing metadata;
- live GUI components or GUI-owned persisted review state;
- production plotting, analysis, fit result model, or scientific judgment;
- numeric dtype conversion, unit conversion, schema inference, scan-shape
  inference, trace opening, or array API;
- external authenticity validation or trusted-source policy;
- package acceptance, retry authorization, rollback policy, or destination
  storage conflict policy;
- recursive linked-context traversal or linked-context durable import;
- shared measurement-record domain model or final storage schema publication.

## Validation And Advancement

Validation evidence for the JNY-001 smoke path lives in
[`../workflow-validation-map.md`](../workflow-validation-map.md). Historical
candidate context lives in Git history.

Advance this boundary only when a named workflow requires broader package-use
behavior, such as production readiness hardening, GUI-owned receiving review
state, archive-backed durable import, durable linked-context import, or
first-class analysis/fit package facts.
