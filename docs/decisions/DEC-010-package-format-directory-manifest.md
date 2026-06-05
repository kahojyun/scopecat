# DEC-010: Use Directory Manifest Packages For The JNY-001 Production Vertical Slice Path

## Status

Decision status: accepted.

Date: 2026-06-03.

## Context

JNY-001 Share A Selected Measurement now has a production vertical slice path:
source-side durable Measurement Record, selected stored-record
export, zip transport creation, zip transport materialization back into the
directory package of record, read-only package open, receiving gate, import
plan, and durable import into a second storage root.

This decision resolves whether that path should introduce an archive file
as the portable package format, or continue to use the current directory-shaped
package with `package-manifest.json`. The package purpose is analysis/review:
carry selected measurement data, declared package members, and visible review
facts for open-before-import inspection.

The slice still needs visible, inspectable artifacts while linked-context
payload import, batch durable import, and final storage schema remain unsettled.
Later DEC-021 and DEC-024 accepted narrow zip transport
materialization and creation, but they keep the DEC-010 directory manifest
package as the package of record rather than making archive bytes authoritative.
It is not an offline execution migration artifact, environment restore, code
restore, or shared lab storage policy.

## Decision

For the JNY-001 single-measurement production vertical slice path, the
portable handoff package remains a directory-shaped package rooted at
`{package_id}/` with `package-manifest.json` at the package root and
package-relative primary data under `measurements/{measurement_record_id}/`.

Archive bytes remain transport-only. Current package writer, opener,
receiving, import-plan, and durable-import paths must continue to treat the
DEC-010 directory manifest package as the package artifact of record. Archive
creation and materialization are governed separately by DEC-024 and DEC-021;
archive-backed durable import and archive bytes as package authority remain
out of scope.

[`DEC-020`](DEC-020-defer-archive-package-implementation.md) keeps
archive-backed durable import, archive bytes as package authority, and broader
archive semantics deferred beyond the DEC-021 materialization and DEC-024
creation boundaries.

## Scope

This decision applies to:

- JNY-001 Share A Selected Measurement production vertical slice path;
- `scopecat.handoff` package writing/opening/receiving/import-plan behavior;
- selected stored Measurement Record export into handoff packages;
- workflow-level tests that validate package format posture.

This decision does not apply to:

- final public package format for all handoff use cases;
- archive bytes as package authority, external authenticity, or trust policy;
- linked-context payload packaging;
- batch export/import package shape;
- offline execution migration packages;
- code or environment restoration;
- shared lab storage semantics;
- GUI or SDK packaging contracts.

## Consequences

This makes the current production vertical slice path easier to inspect,
test, debug, and review after archive transport because the materialized
directory remains the reviewed package of record. It keeps checksum and
integrity behavior focused on declared package members.

It also means any future archive expansion must define whether archive bytes
become authoritative and how durable import is gated from archive-backed flows,
as required by DEC-020. Any external signing or authenticity mechanism remains
outside Scopecat's package format.

## Alternatives Considered

- Option: make a `.zip` or similar archive the package artifact of record.
  Rejected because archive-backed durable-import semantics are not accepted,
  and archive authority would obscure the current package boundary.
- Option: support archive bytes and directory packages as equal package inputs.
  Rejected because dual authority would broaden test and error-contract scope
  before one production vertical slice package contract is stable.
- Option: make archive mandatory for receiving. Rejected because the current
  receiving/import path already validates package-local integrity from a
  materialized directory package and does not need archive bytes as package
  authority.

## Supersession

Supersedes:

- none.

Superseded by:

- none.

## Review Triggers

Revisit this decision when:

- handoff packages need archive bytes to become package authority rather than
  transport containers;
- linked-context payload packaging needs atomic package transfer;
- batch export/import needs a stable bundle format;
- package publication, SDK, or GUI workflows require an archive artifact beyond
  DEC-020.

## Related Evidence

- [`../../engineering/prototype-boundaries/handoff.md`](../engineering/prototype-boundaries/handoff.md)
- [`../../engineering/workflow-validation-map.md`](../engineering/workflow-validation-map.md)
- [`../../../src/scopecat/handoff/README.md`](../../src/scopecat/handoff/README.md)
- [`DEC-020-defer-archive-package-implementation.md`](DEC-020-defer-archive-package-implementation.md)
