# DEC-011: Treat JNY-001 Directory Packages As Unsigned Integrity Evidence

## Status

Decision type: architecture.

Decision status: accepted.

Date: 2026-06-03.

Owner: [`../../engineering/prototype-boundaries/handoff.md`](../../engineering/prototype-boundaries/handoff.md).

## Context

[`DEC-010`](DEC-010-package-format-directory-manifest.md) keeps the JNY-001
single-measurement production vertical slice candidate on a directory manifest
package format. The next architecture pressure is whether that package should
claim authenticity or trust, or whether the current slice should remain limited
to local integrity observation.

The current handoff path can prove useful facts without signatures: package
members are package-relative, declared primary data bytes can be checksummed,
receiving review facts must match the opened package, and durable import is
delegated only after an approved import plan. Those checks do not identify a
trusted signer, prove source authenticity, authorize a sender, or make claims
about scientific validity.

Introducing signatures now would require signer identity, key distribution,
trust roots, revocation, manifest coverage, archive or directory signing
semantics, failure classification, and user-facing review policy. Those
contracts should not be implied by digest verification alone.

## Decision

For the JNY-001 single-measurement production vertical slice candidate,
directory manifest handoff packages remain unsigned local-review evidence.

Scopecat may observe declared package-member integrity with SHA-256 digests and
may gate receiving/import planning on that integrity observation. It must not
present that observation as signature validation, authenticity validation,
sender trust, trusted-source acceptance, or scientific validity.

Current export, package open, integrity observation, receiving gate,
import-plan, and durable-import receipts must continue to expose this
separation with explicit `not_performed` policy fields or `does_not_claim`
entries.

[`DEC-019`](DEC-019-defer-package-signature-trust-implementation.md) keeps
signature/trust implementation deferred until a signed-artifact, canonicalized
coverage, signer identity, and trust-root contract exists.
The current signature/trust contract-review helper records that separation as
local review evidence only; it does not perform signature verification,
trusted-source acceptance, or signature-gated durable import.

## Scope

This decision applies to:

- JNY-001 single-measurement handoff production vertical slice candidate;
- DEC-010 directory manifest packages;
- handoff package writer/open/integrity/receiving/import-plan/durable-import
  local receipts;
- workflow-level tests that validate trust/authenticity posture.

This decision does not apply to:

- final public handoff package trust policy;
- real signature format or manifest coverage;
- key management, signer identity, revocation, or trust roots;
- archive signing or transport security;
- package publication, SDK, or GUI trust presentation;
- scientific validity or domain correctness of the measurement.

## Consequences

This keeps the production vertical slice candidate honest: digest verification can block
corrupted package bytes, while authenticity and trust remain separate future
work. It also keeps receiving/import behavior reviewable without adding a
partial or misleading security model.

Future signature/authenticity work must define the signer identity model, trust
root, signature coverage, unsigned-package handling, retry/error contract, and
how those facts appear in receiving review as required by DEC-019.

## Alternatives Considered

- Option: treat declared digest verification as package trust. Rejected because
  a matching digest only compares package bytes to manifest declarations; it
  does not prove who authored the package or whether the signer is trusted.
- Option: add a placeholder signature field now. Rejected because placeholder
  signature metadata would create schema pressure without a validated trust
  root, signer model, or coverage rule.
- Option: block all import from unsigned packages. Rejected for this slice
  because the current workflow is a local review/import path and has not yet
  accepted a trust policy that requires signatures.

## Supersession

Supersedes:

- none.

Superseded by:

- none.

## Review Triggers

Revisit this decision when:

- packages need to cross a sender/receiver trust boundary;
- package publication or external sharing needs signer identity;
- GUI receiving review needs to explain trusted, untrusted, and unsigned
  package states;
- archive packaging or transport security is introduced;
- durable import policy needs to require a trusted package before mutation.

## Related Evidence And Owners

- [`DEC-010-package-format-directory-manifest.md`](DEC-010-package-format-directory-manifest.md)
- [`DEC-019-defer-package-signature-trust-implementation.md`](DEC-019-defer-package-signature-trust-implementation.md)
- [`../../engineering/prototype-boundaries/handoff.md`](../../engineering/prototype-boundaries/handoff.md)
- [`../../engineering/workflow-validation-map.md`](../../engineering/workflow-validation-map.md)
- [`../../../tests/prototypes/handoff/test_handoff_jny001_single_measurement_workflow.py`](../../../tests/prototypes/handoff/test_handoff_jny001_single_measurement_workflow.py)
