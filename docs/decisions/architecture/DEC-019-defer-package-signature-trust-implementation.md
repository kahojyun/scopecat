# DEC-019: Defer Package Signature And Trust Implementation

## Status

Decision type: architecture.

Decision status: accepted.

Date: 2026-06-03.

Owner: [`../../engineering/prototype-boundaries/handoff.md`](../../engineering/prototype-boundaries/handoff.md).

## Context

[`DEC-011`](DEC-011-package-trust-authenticity-posture.md) defines the current
JNY-001 package trust posture: directory manifest packages are unsigned
local-review evidence, and declared digest integrity must not be presented as
signature validation, source authenticity, sender trust, or scientific
validity.

The selected stored-record export, receiving gate, import plan, durable-import
adapter, and receiving review state projection now form a production
vertical-slice candidate. This decision resolves whether to start implementing
a signature surface now, or explicitly keep signature/trust outside the slice
until the signed-artifact contract is defined.

A partial implementation would be misleading. Signature support needs more than
a manifest field: it must define what bytes are signed, how those bytes are
canonicalized, who signs, which trust roots are accepted, when verification
runs, how failed or missing signatures affect receiving and import, and how
directory packages relate to future archive packages.

## Decision

Do not implement package signatures, signature verification, trusted-source
acceptance, signer identity, key management, trust roots, revocation, or
signature-gated durable import in the current JNY-001 production vertical slice
candidate.

Keep the current package contract at declared digest integrity plus explicit
non-claims. Package ids, source export ids, labels, display names, context
references, package-relative paths, and receiving review facts remain reviewed
package facts; they are not authenticated identity or trusted-source proof.

DEC-022 later accepts the signed content scope as the DEC-010 package of
record: the manifest plus every manifest-declared package member. Any future
signature/trust implementation must still define:

- canonicalization rules for the DEC-010 package of record;
- signer identity, signer metadata, and key material representation;
- trust-root configuration, rotation, revocation, and timestamp expectations;
- verification timing for package open, receiving review, import planning, and
  durable import;
- failure classifications for missing, invalid, stale, unknown, or untrusted
  signatures;
- unsigned-package handling and whether unsigned packages can still be locally
  reviewed;
- user-facing review language that keeps integrity, authenticity, sender trust,
  and scientific validity separate;
- relationship to [`DEC-010`](DEC-010-package-format-directory-manifest.md)
  directory packages and DEC-021 archive materialization.

The current implementation exposes
`current_handoff_signature_trust_contract()` and
`review_handoff_signature_trust_contract()` as local contract-review surfaces.
They do not verify signatures, accept trusted sources, manage keys, configure
trust roots, or gate durable import. They only classify future signature/trust
contract candidates against the DEC-022 signed scope and the required canonical
artifact, canonicalization, signer identity, trust-root, verification-timing,
failure-classification, unsigned-handling, and durable-import gate posture.

## Scope

This decision applies to:

- JNY-001 single-measurement handoff production vertical slice candidate;
- DEC-010 directory manifest packages;
- selected stored-record export and route-local package writer input;
- read-only package open, integrity observation, receiving gate, import plan,
  receiving review state, and durable-import adapter behavior;
- workflow documentation and tests that state signature/trust posture.

This decision does not apply to:

- a future signed package format decision;
- future archive package creation, extraction, or archive signing;
- external PKI, organizational trust policy, or transport security;
- scientific validity, domain correctness, or collaborator review policy;
- public package publication or SDK distribution policy.

## Consequences

The current slice remains honest and testable: corrupted package bytes can be
blocked through declared digest integrity, while authenticity and sender trust
remain unclaimed.

This avoids shipping a placeholder security model that users might mistake for
trust. It also keeps archive-package work, GUI trust presentation, and durable
import mutation policy free to choose the correct trust contract later.

The cost is that cross-organization or adversarial sharing remains out of
scope. A receiver can locally inspect and import reviewed package bytes, but
Scopecat does not yet prove who authored the package or whether that author is
trusted.

## Alternatives Considered

- Option: add an optional signature field to the current manifest. Rejected
  because it would constrain the schema before canonicalization, coverage,
  signer identity, and trust-root semantics exist.
- Option: verify a detached digest file as a lightweight signature. Rejected
  because digest agreement still does not establish signer identity or trusted
  origin.
- Option: block durable import from unsigned packages now. Rejected because
  the current accepted workflow is local review plus explicit import approval,
  not an authenticated sender workflow.
- Option: implement signatures only for single-measurement directory packages.
  Rejected because archive format and multi-measurement packaging are already
  visible requirements, and a narrow signature format could become incompatible
  with the next package-format decision.

## Supersession

Supersedes:

- none.

Superseded by:

- none.

## Review Triggers

Revisit this decision when:

- package exchange must cross a collaborator, organization, publication, or
  adversarial trust boundary;
- DEC-022 signed scope must change;
- archive package creation or extraction is accepted;
- GUI receiving review needs trusted, untrusted, unsigned, and unverifiable
  package states;
- durable import policy must require trusted package evidence before mutation;
- a public SDK or package publishing workflow needs source authenticity.

## Related Evidence And Owners

- [`DEC-010-package-format-directory-manifest.md`](DEC-010-package-format-directory-manifest.md)
- [`DEC-020-defer-archive-package-implementation.md`](DEC-020-defer-archive-package-implementation.md)
- [`DEC-022-define-signed-package-trust-scope.md`](DEC-022-define-signed-package-trust-scope.md)
- [`DEC-011-package-trust-authenticity-posture.md`](DEC-011-package-trust-authenticity-posture.md)
- [`DEC-018-define-receiving-review-state-contract.md`](DEC-018-define-receiving-review-state-contract.md)
- [`../../engineering/prototype-boundaries/handoff.md`](../../engineering/prototype-boundaries/handoff.md)
- [`../../engineering/prototype-boundaries/handoff-durable-import-storage.md`](../../engineering/prototype-boundaries/handoff-durable-import-storage.md)
- [`../../engineering/workflow-validation-map.md`](../../engineering/workflow-validation-map.md)
- [`../../../src/scopecat/handoff/signature_trust.py`](../../../src/scopecat/handoff/signature_trust.py)
