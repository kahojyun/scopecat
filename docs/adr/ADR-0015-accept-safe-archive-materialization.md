# ADR-0015: Accept Safe Archive Materialization

## Status

ADR status: accepted.

## Context

ADR-0014 deferred archive package implementation until archive artifact authority,
safe staging, and materialization review contracts existed. JNY-001 now has a
directory-manifest package of record, receiving review, import planning, durable
import, and selected-record export hardening. Moving a package between machines
as one archive file must not treat archive bytes as the package of record.

ADR-0016 later accepts safe zip archive creation from an openable ADR-0006
directory package. This decision remains the receiving-side materialization
boundary.

## Decision

Accept a narrow archive materialization implementation candidate:

- only zip archive input is materialized;
- archive bytes remain a transport container only;
- the materialized ADR-0006 directory-manifest package remains the package of
  record;
- materialization writes into a caller-provided empty destination under
  `no_overwrite`;
- member paths must stay under the declared package directory;
- absolute paths, parent traversal, duplicate normalized members, symlink
  members, hidden metadata members, missing manifests, and destination
  collisions block materialization;
- failed materialization removes the partial package directory when possible;
- the materialized package must open through the ADR-0006 package opener before
  the receipt reports success.

## Non-Goals

This decision does not implement:

- archive creation, which is accepted separately by ADR-0016;
- external authenticity or trusted-source validation;
- archive-backed durable import;
- package acceptance;
- final public SDK or final package format;
- resource-limit enforcement beyond the local safety checks in this candidate.

## Consequences

Receiving workflows may now stage a zip transport archive into a ADR-0006 package
directory before package open and integrity review. Existing directory package
flows remain valid. Durable import still operates on reviewed package/import-plan
evidence rather than archive bytes.

## Alternatives Considered

- Continue deferring archive materialization entirely. Rejected because it
  leaves the JNY-001 transfer workflow dependent on directory copies.
- Treat the archive file as the package artifact of record. Rejected because it
  would require archive-byte authority not accepted here.
- Extract archives directly into durable Measurement Records storage. Rejected
  because archive materialization must precede package open, review, and import
  planning.

## Related

- [`ADR-0006-package-format-directory-manifest.md`](ADR-0006-package-format-directory-manifest.md)
- [`ADR-0014-defer-archive-authority-and-archive-backed-durable-import.md`](ADR-0014-defer-archive-authority-and-archive-backed-durable-import.md)
- [`ADR-0016-accept-safe-archive-creation.md`](ADR-0016-accept-safe-archive-creation.md)
