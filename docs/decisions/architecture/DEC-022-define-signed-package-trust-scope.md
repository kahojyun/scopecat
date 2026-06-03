# DEC-022: Define Signed Package Trust Scope

## Status

Accepted

## Context

DEC-011 keeps JNY-001 handoff packages at unsigned declared-digest integrity:
digest checks can prove that package members match the manifest, but they do
not prove source authenticity, sender trust, or scientific validity.

DEC-019 intentionally deferred signature/trust implementation because a
placeholder signature field would be misleading without a signed scope,
canonical artifact, canonicalization rules, signer identity, trust roots,
verification timing, and failure policy. DEC-021 then accepted zip archive
materialization while preserving the DEC-010 directory-manifest package as the
package of record.

The next useful step is to decide the scope that a future signature/trust
implementation must satisfy without implementing cryptographic verification or
trusted-source acceptance in the current slice.

## Decision

A future JNY-001 package signature must cover the DEC-010 directory-manifest
package of record, not transport archive bytes and not a digest-only sidecar.
The accepted signed content scope is the manifest plus every manifest-declared
package member. The canonical artifact remains the materialized DEC-010
directory-manifest package.

Archive bytes remain transport containers. A zip archive may be materialized
under DEC-021, but trust decisions must be made against the opened DEC-010
package of record unless a later decision explicitly accepts archive-byte
artifact authority.

Unsigned packages remain locally reviewable but not trusted. A missing,
invalid, stale, unknown-signer, or untrusted-signer signature must not be
silently upgraded into trusted-source evidence. Durable import remains gated by
local review and approval until a later decision accepts signer identity, trust
roots, verification timing, failure handling, and import mutation policy.

## Non-Goals

This decision does not implement:

- signature creation;
- signature verification;
- signer identity validation;
- key management or trust-root configuration;
- revocation, timestamp, or transparency-log policy;
- signature-gated durable import;
- archive-byte signing or archive-backed durable import;
- public SDK or cross-organization trust policy.

## Consequences

The current implementation can keep exposing local signature/trust contract
review without claiming authenticity. Review candidates that propose
`manifest_and_declared_members` or `dec010_directory_manifest_package` as the
signed scope are aligned with the accepted scope, while digest-only,
manifest-only, and archive-byte proposals remain blocked.

This gives future implementation work a stable target: canonicalize and verify
the DEC-010 package of record after safe archive materialization and before any
trusted-source claim. It also avoids blocking current users from carrying
packages between machines, because unsigned packages continue to support local
review and explicit import approval.

## Alternatives Considered

- Sign only the manifest. Rejected because manifest-only signatures do not bind
  the package members that carry the measurement data and linked payloads.
- Sign only declared digests. Rejected because digest agreement alone still
  does not establish signer identity or trusted-source evidence.
- Sign zip archive bytes. Rejected for the current scope because DEC-021 treats
  archive bytes as transport only, not the package artifact of record.
- Require signatures before durable import now. Rejected because DEC-019 still
  defers signer identity, trust roots, verification timing, and import mutation
  policy.

## Related

- [`DEC-010-package-format-directory-manifest.md`](DEC-010-package-format-directory-manifest.md)
- [`DEC-011-package-trust-authenticity-posture.md`](DEC-011-package-trust-authenticity-posture.md)
- [`DEC-019-defer-package-signature-trust-implementation.md`](DEC-019-defer-package-signature-trust-implementation.md)
- [`DEC-021-accept-safe-archive-materialization.md`](DEC-021-accept-safe-archive-materialization.md)
- [`../../engineering/prototype-boundaries/handoff.md`](../../engineering/prototype-boundaries/handoff.md)
- [`../../../src/scopecat/handoff/signature_trust.py`](../../../src/scopecat/handoff/signature_trust.py)
