# DEC-011: Treat JNY-001 Directory Packages As Declared Integrity Evidence

## Status

Decision type: architecture.

Decision status: accepted.

Date: 2026-06-03.

Owner: [`../../engineering/prototype-boundaries/handoff.md`](../../engineering/prototype-boundaries/handoff.md).

## Context

[`DEC-010`](DEC-010-package-format-directory-manifest.md) keeps the JNY-001
single-measurement production vertical slice candidate on a directory manifest
package format. This decision resolves whether that package should claim
authenticity or trust, or whether the current slice should remain limited to
local integrity observation.

The current handoff path can prove useful package-local facts: package members
are package-relative, declared primary data bytes can be checksummed, receiving
review facts must match the opened package, and durable import is delegated
only after an approved import plan. Those checks do not prove source
authenticity, authorize a sender, or make claims about scientific validity.

Handoff package signing is not a Scopecat-owned product requirement for this
workflow. If a lab needs signing or provenance guarantees, those mechanisms can
wrap or accompany Scopecat package artifacts outside Scopecat.

## Decision

For the JNY-001 single-measurement production vertical slice candidate,
directory manifest handoff packages remain declared-integrity local-review
evidence.

Scopecat may observe declared package-member integrity with SHA-256 digests and
may gate receiving/import planning on that integrity observation. It must not
present that observation as authenticity validation, sender trust,
trusted-source acceptance, or scientific validity.

Current export, package open, integrity observation, receiving gate,
import-plan, and durable-import receipts must continue to expose this
separation with explicit `not_performed` policy fields or `does_not_claim`
entries.

## Scope

This decision applies to:

- JNY-001 single-measurement handoff production vertical slice candidate;
- DEC-010 directory manifest packages;
- handoff package writer/open/integrity/receiving/import-plan/durable-import
  local receipts;
- workflow-level tests that validate trust/authenticity posture.

This decision does not apply to:

- final public handoff package trust policy;
- external authenticity, signing, provenance, or transport security mechanisms;
- package publication, SDK, or GUI trust presentation;
- scientific validity or domain correctness of the measurement.

## Consequences

This keeps the production vertical slice candidate honest: digest verification
can block corrupted package bytes, while authenticity and trust remain outside
the accepted package contract. It also keeps receiving/import behavior
reviewable without adding a partial or misleading security model.

## Alternatives Considered

- Option: treat declared digest verification as package trust. Rejected because
  a matching digest only compares package bytes to manifest declarations; it
  does not prove who authored the package or whether an external trust system
  accepts it.
- Option: add Scopecat-owned signing metadata now. Rejected because users do
  not need package signatures inside Scopecat, and labs that need signing can
  use external tools without changing the package contract.

## Supersession

Supersedes:

- none.

Superseded by:

- none.

## Review Triggers

Revisit this decision when:

- packages need to cross a sender/receiver trust boundary;
- package publication or external sharing needs Scopecat to display external
  provenance facts without validating them;
- GUI receiving review needs to explain external trust facts supplied by a
  non-Scopecat system;
- durable import policy needs to require a trusted package before mutation.

## Related Evidence And Owners

- [`DEC-010-package-format-directory-manifest.md`](DEC-010-package-format-directory-manifest.md)
- [`../../engineering/prototype-boundaries/handoff.md`](../../engineering/prototype-boundaries/handoff.md)
- [`../../engineering/workflow-validation-map.md`](../../engineering/workflow-validation-map.md)
- [`../../../tests/prototypes/handoff/test_handoff_jny001_single_measurement_workflow.py`](../../../tests/prototypes/handoff/test_handoff_jny001_single_measurement_workflow.py)
