# DEC-010: Use Directory Manifest Packages For JNY-001 Production Vertical Slice Candidate

## Status

Decision type: architecture.

Decision status: accepted.

Date: 2026-06-03.

Owner: [`../../engineering/prototype-boundaries/handoff.md`](../../engineering/prototype-boundaries/handoff.md).

## Context

JNY-001 now has a single-measurement handoff production vertical slice
candidate: source-side durable Measurement Record, selected stored-record
export, read-only package open, receiving gate, import plan, and durable import
into a second storage root.

The next architecture pressure is whether that candidate should introduce an
archive file as the portable package format, or continue to use the current
directory-shaped package with `package-manifest.json`.

The slice still needs visible, inspectable artifacts while package manifest
shape, trust/authenticity, linked-context payload packaging, batch import, and
final storage schema remain unsettled. Introducing an archive now would add
archive creation, extraction, temporary directory, path traversal, signature,
and retry surface before those contracts are ready.

## Decision

For the JNY-001 single-measurement production vertical slice candidate, the
portable handoff package remains a directory-shaped package rooted at
`{package_id}/` with `package-manifest.json` at the package root and
package-relative primary data under `measurements/{measurement_record_id}/`.

Archive creation and archive extraction remain out of scope. Current package
writer, opener, receiving, import-plan, and durable-import paths must continue
to state archive handling as `not_performed`.

[`DEC-020`](DEC-020-defer-archive-package-implementation.md) keeps archive
creation, archive extraction, archive input opening, and archive-backed durable
import deferred until archive artifact authority, extraction safety, staging,
and materialization review contracts exist.

## Scope

This decision applies to:

- JNY-001 single-measurement handoff production vertical slice candidate;
- `scopecat.handoff` package writing/opening/receiving/import-plan behavior;
- selected stored Measurement Record export into handoff packages;
- workflow-level tests that validate package format posture.

This decision does not apply to:

- final public package format for all handoff use cases;
- compressed archive format, signatures, authenticity, or trust policy;
- linked-context payload packaging;
- batch export/import package shape;
- offline execution migration packages;
- GUI or SDK packaging contracts.

## Consequences

This makes the current production vertical slice candidate easier to inspect, test,
debug, and review without archive extraction or temporary materialization. It
keeps checksum and integrity behavior focused on declared package members.

It also means a future archive decision must define archive member topology,
path traversal protections, extraction/staging semantics, signature or trust
scope, and whether the directory manifest remains the canonical inner format,
as required by DEC-020.

## Alternatives Considered

- Option: create a `.zip` or similar archive now. Rejected for this slice
  because archive extraction, trust, and signature semantics are not yet
  validated and would obscure the current package boundary.
- Option: support both directory and archive inputs now. Rejected because dual
  format support would broaden test and error-contract scope before one
  production vertical slice package contract is stable.
- Option: make archive mandatory for receiving. Rejected because the current
  receiving/import path already validates package-local integrity from a
  directory package and does not yet need offline archive transport semantics.

## Supersession

Supersedes:

- none.

Superseded by:

- none.

## Review Triggers

Revisit this decision when:

- handoff packages need to cross a transport boundary where directories are not
  acceptable;
- signed package or trusted-source policy work beyond DEC-019 starts;
- linked-context payload packaging needs atomic package transfer;
- batch export/import needs a stable bundle format;
- package publication, SDK, or GUI workflows require an archive artifact beyond
  DEC-020.

## Related Evidence And Owners

- [`../../engineering/prototype-boundaries/handoff.md`](../../engineering/prototype-boundaries/handoff.md)
- [`../../engineering/workflow-validation-map.md`](../../engineering/workflow-validation-map.md)
- [`../../../src/scopecat/handoff/README.md`](../../../src/scopecat/handoff/README.md)
- [`DEC-020-defer-archive-package-implementation.md`](DEC-020-defer-archive-package-implementation.md)
