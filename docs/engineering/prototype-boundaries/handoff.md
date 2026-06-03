# Handoff Package-Use Prototype Boundary

## Status

Accepted engineering-prototype boundary.

## Purpose

This note owns the current package-use boundary for `scopecat.handoff`: writing
Scopecat-authored package directories from caller-declared source files,
exporting selected stored Measurement Records to packages, opening packages
read-only, producing local review surfaces, running receiving gates, and
building non-mutating import plans.

Read it with:

- [`../../../src/scopecat/handoff/README.md`](../../../src/scopecat/handoff/README.md)
  for live API and CLI orientation;
- [`handoff-durable-import-storage.md`](handoff-durable-import-storage.md) for
  the separate durable Measurement Records import adapter boundary;
- [`../../decisions/architecture/DEC-010-package-format-directory-manifest.md`](../../decisions/architecture/DEC-010-package-format-directory-manifest.md)
  for the current package format decision;
- [`../../decisions/architecture/DEC-011-package-trust-authenticity-posture.md`](../../decisions/architecture/DEC-011-package-trust-authenticity-posture.md)
  for the current package trust/authenticity posture;
- [`../../decisions/architecture/DEC-012-linked-context-payload-packaging.md`](../../decisions/architecture/DEC-012-linked-context-payload-packaging.md)
  for the current route-local linked-context payload boundary;
- [`../../decisions/architecture/DEC-013-batch-receiving-import-planning.md`](../../decisions/architecture/DEC-013-batch-receiving-import-planning.md)
  for the current batch receiving/import planning boundary;
- [`../../decisions/architecture/DEC-014-selected-record-linked-context-payload-export.md`](../../decisions/architecture/DEC-014-selected-record-linked-context-payload-export.md)
  for the current selected-record linked-context payload export boundary;
- [`../../decisions/architecture/DEC-015-selected-record-batch-package-export.md`](../../decisions/architecture/DEC-015-selected-record-batch-package-export.md)
  for the current selected-record batch export boundary;
- [`../../decisions/architecture/DEC-016-defer-linked-context-payload-import.md`](../../decisions/architecture/DEC-016-defer-linked-context-payload-import.md)
  for the current durable linked-context payload import deferral;
- [`../../decisions/architecture/DEC-017-defer-batch-durable-import.md`](../../decisions/architecture/DEC-017-defer-batch-durable-import.md)
  for the current batch durable import deferral;
- [`../../decisions/architecture/DEC-018-define-receiving-review-state-contract.md`](../../decisions/architecture/DEC-018-define-receiving-review-state-contract.md)
  for the current receiving review state projection boundary;
- [`../../decisions/architecture/DEC-019-defer-package-signature-trust-implementation.md`](../../decisions/architecture/DEC-019-defer-package-signature-trust-implementation.md)
  for the current package signature/trust implementation deferral;
- [`../../decisions/architecture/DEC-020-defer-archive-package-implementation.md`](../../decisions/architecture/DEC-020-defer-archive-package-implementation.md)
  for the current archive package implementation deferral;
- [`../workflow-validation-map.md`](../workflow-validation-map.md) for the
  current cross-capability handoff workflow gap.

## Current Boundary

The accepted package-use flow is:

```text
caller-declared source root and package write request
  -> source-root package writer
  -> directory-shaped package subset
  -> manifest validation and preview classification
  -> read-only package open
  -> local inspection or workflow receipt
  -> receiving gate
  -> non-mutating import plan
```

The selected stored-record export adapter composes with that package writer:

```text
complete Measurement Record read model and record-local receipts
  -> selected-record export request with explicit preview metadata
  -> package writer request
  -> directory-shaped selected-measurement package
  -> read-only package open
```

This boundary owns package artifact creation and read-only package review. It
does not own durable storage mutation; durable import is delegated through
[`handoff-durable-import-storage.md`](handoff-durable-import-storage.md).

## Supported Behavior

The current package writer:

- requires an approved package write request;
- accepts a caller-provided `source_root` and declared relative primary-data
  paths;
- validates digest and size facts before copying primary CSV files;
- writes the current directory-shaped package subset and deterministic
  `package-manifest.json`;
- uses no-overwrite collision behavior;
- can package explicitly declared linked-context payloads under `context/` or
  keep linked context reference-only;
- returns a local write receipt;
- proves generated packages open through the read-only opener.

The package writer is a route-local capability, not the normal JNY-001 product
handoff entrypoint. Caller-declared package ids, measurement ids, and
linked-context ids are reviewed package-input facts. They are not durable
Scopecat Measurement Record identity and do not replace storage lifecycle
evidence, record-local read models, creation manifests, or writer receipts.

The selected stored-record export adapter:

- requires an approved selected-record export request;
- reads one complete Measurement Records read model plus record-local creation
  and writer receipts;
- preserves record id, record-local primary-data path, digest, size, label,
  and experiment type into the package writer request;
- requires explicit preview metadata and does not infer plot semantics from CSV
  headers;
- can package explicitly declared record-local linked-context payloads under
  `context/` after digest and size preflight;
- writes one package through the package writer: single-measurement for a
  single export request, or multi-measurement for a batch export request that
  selects multiple complete stored records;
- keeps non-declared linked context reference-only and does not treat recorded
  references as payload authority;
- does not mutate Measurement Records storage or refresh read models.

Selected-record export receipts include local `export_review` guidance for
successful transfer review or blocked retry review. That guidance classifies
request approval gaps, package destination collisions, missing record evidence,
record evidence mismatches, incomplete records, and record path scope
violations. It does not authorize retry or mutate storage.

For JNY-001 product handoff, this storage-backed selected-record export path is
the production vertical slice candidate. Direct package-writer input remains an
adapter or engineering route for already-reviewed normalized data, not a
user-facing bypass around Measurement Records storage.

The current read-only package use:

- validates raw manifest dictionaries at the package boundary;
- uses typed route-local manifest fragments after validation;
- projects package, measurement, table, declared plot, finding, and
  linked-context review facts;
- opens package-local primary CSV data for `preview_ready` measurements;
- treats declared preview metadata as preview authority;
- preserves package id and package-directory continuity;
- uses `measurements/{measurement_record_id}/primary.csv` as the canonical
  primary-data package topology;
- can write local static inspection HTML outside the package tree.

The receiving path:

- observes manifest-declared package integrity read-only;
- runs an approved receiving gate before import planning;
- checks reviewed package id, preview classification, and integrity facts;
- builds a non-mutating import plan over selected package measurements,
  including multiple measurements when requested;
- lists package-local primary data and linked-context reference handling for a
  later acceptance or durable-import decision;
- records blocked plans without destination, storage mutation, conflict policy,
  or rollback behavior.

Receiving gate and import-plan receipts include local review guidance for
successful continuation or blocked retry review. That guidance classifies
integrity-review blocks and receiving-gate readiness before durable import is
considered. It does not authorize retry, package acceptance, or storage
mutation.

Public receiving and import-planning API functions promote route contract
failures to `HandoffContractError`, which remains `ValueError`-compatible.
`to_diagnostic()` exposes a local operator diagnostic with operation, code, and
message. That diagnostic is a local review surface only; it is not a
portable/export artifact, retry authorization, package acceptance, storage
mutation authority, or public error schema.

`current_handoff_compatibility_contract()` exposes a copy-safe local snapshot
of current route schemas, policy fields, local artifact postures, error
diagnostic posture, and explicit non-claims. It is a route-local compatibility
review surface for this production vertical slice only. It does not define a
public SDK, final package format, archive contract, signature/trust policy, or
portable error schema.

The CLI may print `HandoffErrorDiagnostic` JSON to stderr for handoff
receipt-summary contract failures. That CLI output is local operator guidance
only. It is not a portable/export artifact, retry authorization, package
acceptance, or public CLI error contract.

Receiving review state is a local projection over package-open, integrity,
receiving-gate, import-plan, optional inspection, durable-import receipt, and
retry-summary facts. `project_handoff_receiving_review_state()` implements
that DEC-018 projection as a read-only local summary over typed receipts and
diagnostics. It validates supplied receipt continuity and keeps persisted
GUI-owned state deferred.

## Artifact Authority

The package directory and `package-manifest.json` are portable handoff
artifacts. Package contents must use package-relative paths and validated
managed references at the package/export boundary.

[`DEC-010`](../../decisions/architecture/DEC-010-package-format-directory-manifest.md) keeps this
directory manifest package as the current JNY-001 production vertical slice package
format. Archive creation and extraction remain deferred for a later decision.

[`DEC-020`](../../decisions/architecture/DEC-020-defer-archive-package-implementation.md)
keeps archive creation, extraction, archive input opening, and archive-backed
durable import deferred until archive artifact authority, extraction safety,
staging, and materialization review contracts exist.
`current_handoff_archive_materialization_contract()` records the current
transport-only archive posture: archive bytes are not the package artifact of
record, and any future archive materialization must stage into a DEC-010
directory manifest package before package open and integrity review.

[`DEC-011`](../../decisions/architecture/DEC-011-package-trust-authenticity-posture.md)
keeps this package unsigned local-review evidence. Declared digest integrity
may gate receiving/import planning, but signature validation, authenticity,
sender trust, and scientific validity remain unclaimed.

[`DEC-019`](../../decisions/architecture/DEC-019-defer-package-signature-trust-implementation.md)
keeps signature/trust implementation deferred until a signed-artifact,
canonicalized coverage, signer identity, and trust-root contract exists.
`current_handoff_signature_trust_contract()` records the current unsigned
local-review posture and the required future trust boundary without verifying
signatures, accepting trusted sources, or gating durable import.

Local writer receipts, workflow receipts, inspection HTML, receiving-gate
results, import-plan objects, CLI summaries, and retry reviews are local review
surfaces unless a later slice explicitly promotes one as a portable/export
artifact.

Selected stored Measurement Record export may package request-declared
record-local linked-context payloads under `context/`. The package-use route
may expose linked-context references for review, but it does not recursively
traverse references, restore environments, or import linked context into
durable Measurement Records storage.

[`DEC-012`](../../decisions/architecture/DEC-012-linked-context-payload-packaging.md)
narrows that posture for the generic package writer: explicitly declared
linked-context payload files may be packaged under `context/`, opened as
`packaged_payload`, and integrity-observed. Import planning and durable import
still do not import linked-context payloads.

[`DEC-014`](../../decisions/architecture/DEC-014-selected-record-linked-context-payload-export.md)
extends that posture to selected stored Measurement Record export only when the
export request explicitly declares a record-local source path, `context/`
package path, digest, and byte size. Recorded linked references remain
reference-only review facts unless the request carries that payload authority.

[`DEC-013`](../../decisions/architecture/DEC-013-batch-receiving-import-planning.md)
allows non-mutating import plans to list multiple package measurements. Durable
handoff import remains one planned measurement per storage mutation.

[`DEC-016`](../../decisions/architecture/DEC-016-defer-linked-context-payload-import.md)
keeps linked-context payload import deferred. Packaged linked context remains
reviewable package content; import planning keeps `keep_reference_only` and
durable import does not materialize linked payloads into Measurement Records
storage.

[`DEC-017`](../../decisions/architecture/DEC-017-defer-batch-durable-import.md)
keeps batch durable import deferred. Multi-measurement packages may be reviewed
and planned together, but durable import remains one planned measurement per
storage mutation.

[`DEC-018`](../../decisions/architecture/DEC-018-define-receiving-review-state-contract.md)
defines receiving review state as a derived local projection. The current
projection implementation is local review evidence only; it does not add a
frontend, durable GUI store, or mutation authority.

## Production Vertical Slice Candidate

JNY-001 single-measurement handoff is a production vertical slice candidate when
one workflow-level regression proves this full path:

```text
source-side durable Measurement Record
  -> selected stored-record package export
  -> read-only package open
  -> receiving gate
  -> non-mutating import plan
  -> durable import into a second storage root
```

Acceptance for that candidate is intentionally narrow:

- exactly one selected, complete Measurement Record is exported;
- primary CSV bytes, digest, size, label, experiment type, and record identity
  remain continuous through export and receiving;
- preview metadata is explicit and package-manifest authored;
- stale or missing source-side record evidence blocks export before producing a
  new package;
- existing package destinations use no-overwrite behavior;
- blocked selected-record exports summarize a reviewable next action without
  authorizing retry;
- corrupted package bytes block receiving/import through integrity review;
- blocked receiving and import planning summarize reviewable next actions
  without authorizing retry;
- declared digest integrity remains separate from signature validation,
  authenticity, sender trust, and scientific validity;
- receiving review facts must match the opened package and observed integrity;
- blocked durable imports summarize the next action without authorizing mutation
  and require a fresh import plan for retry review;
- receiving review and import planning remain non-mutating;
- durable storage mutation remains delegated to Measurement Records import;
- durable import receipts and summaries expose reviewable block reasons,
  next actions, and retry requirements without authorizing retry;
- local receipts remain review surfaces, not portable package artifacts;
- selected stored Measurement Record export may package explicitly declared
  record-local linked-context payloads, while durable import keeps linked
  context reference-only.

This candidate is not production readiness for the whole handoff capability.
Persisted GUI/review state, public SDK contracts, and final storage schemas
remain separate decisions. Archive implementation beyond the DEC-010 directory
manifest package format is explicitly deferred by
[`DEC-020`](../../decisions/architecture/DEC-020-defer-archive-package-implementation.md).
Signature/authenticity implementation and trust policy beyond the unsigned
local-review posture are explicitly deferred by
[`DEC-019`](../../decisions/architecture/DEC-019-defer-package-signature-trust-implementation.md).
Generic writer linked-context payload packaging without import is governed by
[`DEC-012`](../../decisions/architecture/DEC-012-linked-context-payload-packaging.md).
Batch import planning without batch durable mutation is governed by
[`DEC-013`](../../decisions/architecture/DEC-013-batch-receiving-import-planning.md).
Selected-record linked-context payload export is governed by
[`DEC-014`](../../decisions/architecture/DEC-014-selected-record-linked-context-payload-export.md).
Selected-record batch export without batch durable import is governed by
[`DEC-015`](../../decisions/architecture/DEC-015-selected-record-batch-package-export.md).
Linked-context payload import deferral is governed by
[`DEC-016`](../../decisions/architecture/DEC-016-defer-linked-context-payload-import.md).
Batch durable import deferral is governed by
[`DEC-017`](../../decisions/architecture/DEC-017-defer-batch-durable-import.md).
Receiving review state projection is governed by
[`DEC-018`](../../decisions/architecture/DEC-018-define-receiving-review-state-contract.md).
Package signature/trust implementation deferral is governed by
[`DEC-019`](../../decisions/architecture/DEC-019-defer-package-signature-trust-implementation.md).
Archive package implementation deferral is governed by
[`DEC-020`](../../decisions/architecture/DEC-020-defer-archive-package-implementation.md).

## Historical Context

Discovery candidates and the older
`measurement_record_directory_candidate_v0` storage-acceptance route remain
historical evidence only. They are useful for review order, approval, receipt,
and rollback pressure, but they are not live runtime dependencies and should
not be extended as the durable Measurement Records import path.

Archived context lives in:

- [`../archive/handoff-prototype-readiness.md`](../archive/handoff-prototype-readiness.md);
- [`../archive/handoff-candidate-storage-acceptance.md`](../archive/handoff-candidate-storage-acceptance.md);
- [`../archive/handoff-storage-import-requirements-synthesis.md`](../archive/handoff-storage-import-requirements-synthesis.md).

## Out Of Scope

This boundary does not accept:

- final public SDK names or package publishing metadata;
- hard pandas/numpy dependency;
- production plotting or publication-grade rendering;
- live GUI components, routing, interaction model, or persisted GUI review
  state beyond DEC-018;
- numeric dtype conversion, unit conversion, schema inference, scan-shape
  inference, trace opening, or array API;
- archive extraction or compressed package format beyond DEC-020;
- signature validation,
  authenticity validation, or trusted-source policy beyond DEC-019;
- durable import, package acceptance, existing-record update, durable
  multi-measurement batch import beyond DEC-017, rollback policy, or storage
  conflict policy;
- recursive traversal or linked-context payload import beyond DEC-016;
- analysis/fit result model, fit execution, uncertainty, write-back, or result
  import;
- shared measurement-record domain model or cross-route object lifecycle.

## Tests And Fixtures

Active prototype tests live under
[`../../../tests/prototypes/handoff/`](../../../tests/prototypes/handoff/).
Handoff fixtures live under
[`../../../tests/fixtures/prototypes/handoff/`](../../../tests/fixtures/prototypes/handoff/)
and selected handoff fixture families under
[`../../../tests/fixtures/`](../../../tests/fixtures/).

Run repository checks with:

```sh
uv run python -m unittest discover -s tests
uv run ruff check .
uv run ruff format --check .
```

## Advancement Questions

Advance this boundary only when a named workflow requires broader package-use
behavior. Current likely separate decisions include:

- production readiness hardening for selected stored Measurement Record export;
- persisted GUI review beyond the DEC-018 local projection boundary;
- archive package creation or extraction beyond DEC-020;
- signed package and trusted-source policy beyond DEC-019;
- durable linked-context payload import beyond DEC-016 or batch durable import
  beyond DEC-017;
- analysis or fit results as first-class package display facts;
- shared lifecycle or domain model extraction justified by more than one
  accepted route.
