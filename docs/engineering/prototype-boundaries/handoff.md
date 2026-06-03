# Handoff Package-Use Prototype Boundary

## Status

Accepted engineering-prototype boundary.

## Purpose

This note owns the current package-use boundary for `scopecat.handoff`: writing
Scopecat-authored package directories from caller-declared source files,
exporting one selected stored Measurement Record to a package, opening
packages read-only, producing local review surfaces, running receiving gates,
and building non-mutating import plans.

Read it with:

- [`../../../src/scopecat/handoff/README.md`](../../../src/scopecat/handoff/README.md)
  for live API and CLI orientation;
- [`handoff-durable-import-storage.md`](handoff-durable-import-storage.md) for
  the separate durable Measurement Records import adapter boundary;
- [`../../decisions/architecture/DEC-010-package-format-directory-manifest.md`](../../decisions/architecture/DEC-010-package-format-directory-manifest.md)
  for the current package format decision;
- [`../../decisions/architecture/DEC-011-package-trust-authenticity-posture.md`](../../decisions/architecture/DEC-011-package-trust-authenticity-posture.md)
  for the current package trust/authenticity posture;
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
  -> directory-shaped single-measurement package
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
- keeps linked context reference-only;
- returns a local write receipt;
- proves generated packages open through the read-only opener.

The selected stored-record export adapter:

- requires an approved selected-record export request;
- reads one complete Measurement Records read model plus record-local creation
  and writer receipts;
- preserves record id, record-local primary-data path, digest, size, label,
  and experiment type into the package writer request;
- requires explicit preview metadata and does not infer plot semantics from CSV
  headers;
- writes a single-measurement package through the package writer;
- keeps linked context reference-only;
- does not mutate Measurement Records storage or refresh read models.

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
- builds a non-mutating import plan over selected package measurements;
- lists package-local primary data and linked-context reference handling for a
  later acceptance or durable-import decision;
- records blocked plans without destination, storage mutation, conflict policy,
  or rollback behavior.

## Artifact Authority

The package directory and `package-manifest.json` are portable handoff
artifacts. Package contents must use package-relative paths and validated
managed references at the package/export boundary.

[`DEC-010`](../../decisions/architecture/DEC-010-package-format-directory-manifest.md) keeps this
directory manifest package as the current JNY-001 production-slice package
format. Archive creation and extraction remain deferred for a later decision.

[`DEC-011`](../../decisions/architecture/DEC-011-package-trust-authenticity-posture.md)
keeps this package unsigned local-review evidence. Declared digest integrity
may gate receiving/import planning, but signature validation, authenticity,
sender trust, and scientific validity remain unclaimed.

Local writer receipts, workflow receipts, inspection HTML, receiving-gate
results, import-plan objects, CLI summaries, and retry reviews are local review
surfaces unless a later slice explicitly promotes one as a portable/export
artifact.

Linked context is reference-only in this boundary. The package-use route may
expose linked-context references for review, but it does not package linked
payloads, recursively traverse references, restore environments, or import
linked context into durable Measurement Records storage.

## Production Vertical-Slice Candidate

JNY-001 single-measurement handoff is a production vertical-slice candidate when
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
- corrupted package bytes block receiving/import through integrity review;
- declared digest integrity remains separate from signature validation,
  authenticity, sender trust, and scientific validity;
- receiving review facts must match the opened package and observed integrity;
- blocked durable imports summarize the next action without authorizing mutation
  and require a fresh import plan for retry review;
- receiving review and import planning remain non-mutating;
- durable storage mutation remains delegated to Measurement Records import;
- local receipts remain review surfaces, not portable package artifacts;
- linked context remains reference-only.

This candidate is not production readiness for the whole handoff capability.
Batch export/import, linked-context payload packaging, persistent GUI/review
state, public SDK contracts, and final storage schemas remain separate
decisions. Archive format is explicitly deferred by
[`DEC-010`](../../decisions/architecture/DEC-010-package-format-directory-manifest.md).
Signature/authenticity implementation and trust policy beyond the unsigned
local-review posture are explicitly deferred by
[`DEC-011`](../../decisions/architecture/DEC-011-package-trust-authenticity-posture.md).

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
- live GUI components, routing, or interaction model;
- numeric dtype conversion, unit conversion, schema inference, scan-shape
  inference, trace opening, or array API;
- archive extraction, compressed package format, signature validation,
  authenticity validation, or trusted-source policy;
- durable import, package acceptance, existing-record update, durable
  multi-measurement batch import, rollback policy, or storage conflict policy;
- linked-context payload packaging, opening, recursive traversal, or import;
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

- production-readiness hardening for selected stored Measurement Record export;
- GUI review beyond local static HTML;
- signature implementation or trusted-source policy beyond DEC-011;
- linked-context payload packaging or review;
- analysis or fit results as first-class package display facts;
- shared lifecycle or domain model extraction justified by more than one
  accepted route.
