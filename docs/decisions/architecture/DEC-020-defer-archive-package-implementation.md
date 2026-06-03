# DEC-020: Defer Archive Package Implementation

## Status

Decision type: architecture.

Decision status: accepted.

Date: 2026-06-03.

Owner: [`../../engineering/prototype-boundaries/handoff.md`](../../engineering/prototype-boundaries/handoff.md).

## Context

[`DEC-010`](DEC-010-package-format-directory-manifest.md) keeps the JNY-001
production vertical-slice candidate on a directory manifest package:
`{package_id}/package-manifest.json` plus package-relative members. That
decision intentionally left archive creation and extraction out of scope.

The handoff workflow now has enough continuity to revisit whether archive
packaging should be implemented next. A portable archive may eventually be the
right transport artifact, especially for collaborators, publication, SDK
distribution, or GUI download/upload flows. But archive support is not a small
format toggle. It introduces archive-member topology, extraction authority,
staging directories, overwrite policy, path traversal protection, duplicate
member handling, symlink behavior, compression/resource limits, integrity
timing, receiving review state, and interaction with any future signature or
trust contract.

The current package directory remains useful as inspectable local-review
evidence. Implementing archive support before those contracts exist would add
failure modes without closing a user-visible acceptance gap in the current
production vertical-slice candidate.

## Decision

Do not implement archive creation, archive extraction, archive input opening,
archive-to-directory materialization, or archive-backed durable import in the
current JNY-001 production vertical-slice candidate.

The current portable package remains the directory manifest package accepted by
DEC-010. Export, writer, open, receiving, import-plan, durable-import, CLI, and
review surfaces must continue to state archive creation or extraction as
`not_performed` or an equivalent explicit non-claim.

Any future archive implementation must first define:

- archive format and extension;
- whether archive bytes or the extracted directory are the portable/export
  artifact of record;
- inner member topology and whether the DEC-010 directory manifest remains the
  canonical inner format;
- safe extraction rules for absolute paths, parent traversal, duplicate names,
  hidden metadata, symlinks, permissions, and platform-specific path behavior;
- staging directory, cleanup, overwrite, collision, and retry policy;
- resource limits for archive size, extracted size, member count, compression
  ratio, and extraction time;
- integrity timing before and after extraction, including which facts are
  observed before package open;
- receiving review state for archive received, extracted, blocked, retried,
  and opened states;
- relationship to DEC-019 signed package and trust-root policy;
- durable-import gating rules after archive materialization.

## Scope

This decision applies to:

- JNY-001 single-measurement handoff production vertical-slice candidate;
- selected stored-record export and route-local package writing;
- package open, integrity observation, receiving gate, import planning,
  receiving review state, and durable-import adaptation;
- CLI and local review surfaces that report archive handling posture;
- workflow documentation and tests that state package format posture.

This decision does not apply to:

- a future accepted archive format;
- public package publication or SDK download/upload workflows;
- external transport security;
- future package signing, signer identity, or trusted-source policy beyond
  DEC-019;
- GUI file-picker, drag/drop, or upload interaction design.

## Consequences

The current handoff slice stays focused on one inspectable artifact shape and
one receiving path. Directory packages remain easy to inspect, test, and debug
while the receiving/import contract is still moving toward production
readiness.

Archive work remains visible but no longer acts as the default next
implementation step. The next handoff pressure should be production-readiness
hardening unless a named workflow explicitly needs archive transport.

The tradeoff is that directory packages are less convenient for transfer than a
single file. Users who need single-file transfer still need external packaging
outside Scopecat until an archive contract is accepted.

## Alternatives Considered

- Option: create a `.zip` archive during export while still opening only
  directories. Rejected because it would create a second artifact with unclear
  authority and no accepted extraction or integrity contract.
- Option: accept archive input by extracting to a temporary directory. Rejected
  because extraction safety, staging cleanup, overwrite, and retry behavior
  would become implicit.
- Option: make archive bytes the canonical package and treat the directory as
  build output. Rejected because signature/trust and archive-byte integrity are
  deferred, and the current readable directory package is the accepted package
  contract.
- Option: implement archive support only for single-measurement packages.
  Rejected because linked-context payloads and multi-measurement package export
  already affect member topology and future extraction review.

## Supersession

Supersedes:

- none.

Superseded by:

- none.

## Review Triggers

Revisit this decision when:

- package exchange must be a single file for collaborator, publication, GUI, or
  SDK workflows;
- a receiving UI needs upload/download semantics rather than a local directory
  path;
- signed package policy beyond DEC-019 chooses archive bytes as the signed
  artifact;
- linked-context payload or multi-measurement package transfer requires atomic
  bundle semantics;
- package publication requires transport-ready artifacts.

## Related Evidence And Owners

- [`DEC-010-package-format-directory-manifest.md`](DEC-010-package-format-directory-manifest.md)
- [`DEC-019-defer-package-signature-trust-implementation.md`](DEC-019-defer-package-signature-trust-implementation.md)
- [`../../engineering/prototype-boundaries/handoff.md`](../../engineering/prototype-boundaries/handoff.md)
- [`../../engineering/prototype-boundaries/handoff-durable-import-storage.md`](../../engineering/prototype-boundaries/handoff-durable-import-storage.md)
- [`../../engineering/workflow-validation-map.md`](../../engineering/workflow-validation-map.md)
- [`../../../src/scopecat/handoff/README.md`](../../../src/scopecat/handoff/README.md)
