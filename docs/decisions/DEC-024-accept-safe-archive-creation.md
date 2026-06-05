# DEC-024: Accept Safe Archive Creation

## Status

Decision status: accepted.

Date: 2026-06-04.

## Context

DEC-021 accepts safe zip archive materialization into a DEC-010
directory-manifest package of record. That gives the receiving side a safe
staging path, but users still need an external tool to create the zip transport
archive from an existing package directory.

Archive creation should not change artifact authority. The DEC-010 directory
package remains the package of record, archive bytes remain transport only, and
receiving must still materialize and open the package before review or import.

## Decision

Accept narrow zip archive creation from an already-openable DEC-010
directory-manifest package:

- only zip archive output is created;
- archive bytes remain a transport container only;
- the source DEC-010 directory-manifest package remains the package of record;
- creation writes to a caller-provided archive path under `no_overwrite`;
- the source package must open through the DEC-010 package opener before archive
  creation;
- archived member paths must be package-relative under the package id root;
- symlink package members, metadata member paths, unsafe member paths, missing
  manifests, and archive destination collisions block creation;
- a created archive should round-trip through DEC-021 materialization into an
  openable DEC-010 package.

## Scope

This decision applies to:

- JNY-001 handoff package transfer ergonomics;
- zip transport archive creation from DEC-010 directory-manifest packages;
- route-local compatibility and prototype tests for archive creation receipts.

This decision does not apply to:

- archive bytes as the package artifact of record;
- archive-backed durable import;
- external authenticity or trust validation;
- package acceptance;
- storage mutation;
- public SDK or final package format;
- resource-limit enforcement beyond the local safety checks in this candidate.

## Consequences

Users can produce one zip file for transfer without making that file the package
authority. Receiving workflows still materialize the archive into the DEC-010
directory package before package open, integrity review, receiving gate, import
planning, or durable import.

The implementation exposes `create_handoff_archive_package_from_request()` as
a local receipt-producing helper. The receipt records archive creation as
transport-only evidence and keeps package acceptance, durable import, storage
mutation, archive-backed import, and external authenticity/trust validation
unclaimed.

## Alternatives Considered

- Continue requiring external zip tools. Rejected because it leaves a practical
  transfer step outside the validated JNY-001 workflow.
- Treat the zip file as the package artifact of record. Rejected because that
  would require archive-byte authority not accepted here.
- Create archives without opening the package first. Rejected because archive
  creation must start from an openable DEC-010 package, not arbitrary folders.

## Supersession

Supersedes:

- none.

Superseded by:

- none.

## Review Triggers

Revisit this decision when:

- archive bytes need to become the package of record;
- archive-backed durable import is proposed;
- public SDK or GUI download behavior needs a stable archive contract;
- resource limits for archive creation must become explicit policy;
- compression policy or deterministic archive bytes are required.

## Related Evidence

- [`DEC-010-package-format-directory-manifest.md`](DEC-010-package-format-directory-manifest.md)
- [`DEC-021-accept-safe-archive-materialization.md`](DEC-021-accept-safe-archive-materialization.md)
- [`../../engineering/prototype-boundaries/handoff.md`](../engineering/prototype-boundaries/handoff.md)
- [`../../engineering/workflow-validation-map.md`](../engineering/workflow-validation-map.md)
- [`../../../src/scopecat/handoff/archive_materialization.py`](../../src/scopecat/handoff/archive_materialization.py)
