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

For JNY-001 product handoff, this storage-backed selected-record export path is
the production vertical-slice candidate. Direct package-writer input remains an
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
- selected stored Measurement Record export may package explicitly declared
  record-local linked-context payloads, while durable import keeps linked
  context reference-only.

This candidate is not production readiness for the whole handoff capability.
Batch durable import, persistent GUI/review state, public SDK contracts, and
final storage schemas remain separate decisions. Archive format is explicitly
deferred by
[`DEC-010`](../../decisions/architecture/DEC-010-package-format-directory-manifest.md).
Signature/authenticity implementation and trust policy beyond the unsigned
local-review posture are explicitly deferred by
[`DEC-011`](../../decisions/architecture/DEC-011-package-trust-authenticity-posture.md).
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

- production-readiness hardening for selected stored Measurement Record export;
- GUI review beyond local static HTML;
- signature implementation or trusted-source policy beyond DEC-011;
- batch durable import or durable linked-context payload import beyond DEC-016;
- analysis or fit results as first-class package display facts;
- shared lifecycle or domain model extraction justified by more than one
  accepted route.
