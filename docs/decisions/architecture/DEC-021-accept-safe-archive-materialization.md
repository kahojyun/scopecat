# DEC-021: Accept Safe Archive Materialization

## Status

Accepted

## Context

DEC-020 deferred archive package implementation until archive artifact authority,
safe staging, and materialization review contracts existed. JNY-001 now has a
directory-manifest package of record, receiving review, import planning, durable
import, signature/trust deferral, and selected-record export hardening. The
remaining practical transfer gap is moving a package between machines as one
archive file without treating archive bytes as the package of record.

## Decision

Accept a narrow archive materialization implementation candidate:

- only zip archive input is materialized;
- archive bytes remain a transport container only;
- the materialized DEC-010 directory-manifest package remains the package of
  record;
- materialization writes into a caller-provided empty destination under
  `no_overwrite`;
- member paths must stay under the declared package directory;
- absolute paths, parent traversal, duplicate normalized members, symlink
  members, hidden metadata members, missing manifests, and destination
  collisions block materialization;
- failed materialization removes the partial package directory when possible;
- the materialized package must open through the DEC-010 package opener before
  the receipt reports success.

## Non-Goals

This decision does not implement:

- archive creation;
- signature, authenticity, signer identity, or trusted-source validation;
- archive-backed durable import;
- package acceptance;
- final public SDK or final package format;
- resource-limit enforcement beyond the local safety checks in this candidate.

## Consequences

Receiving workflows may now stage a zip transport archive into a DEC-010 package
directory before package open and integrity review. Existing directory package
flows remain valid. DEC-019 still governs signature/trust deferral, and durable
import still operates on reviewed package/import-plan evidence rather than
archive bytes.

## Alternatives Considered

- Continue deferring archive materialization entirely. Rejected because it
  leaves the JNY-001 transfer workflow dependent on directory copies.
- Treat the archive file as the package artifact of record. Rejected because it
  would require a signed archive/canonical byte contract not accepted here.
- Extract archives directly into durable Measurement Records storage. Rejected
  because archive materialization must precede package open, review, and import
  planning.

## Related

- [`DEC-010-package-format-directory-manifest.md`](DEC-010-package-format-directory-manifest.md)
- [`DEC-019-defer-package-signature-trust-implementation.md`](DEC-019-defer-package-signature-trust-implementation.md)
- [`DEC-020-defer-archive-package-implementation.md`](DEC-020-defer-archive-package-implementation.md)
