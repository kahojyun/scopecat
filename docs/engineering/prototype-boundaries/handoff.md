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
  for live API orientation;
- [`handoff-durable-import-storage.md`](handoff-durable-import-storage.md) for
  the separate durable Measurement Records import adapter boundary;
- [`../../adr/ADR-0006-package-format-directory-manifest.md`](../../adr/ADR-0006-package-format-directory-manifest.md)
  for the current package format decision;
- [`../../adr/ADR-0007-package-trust-authenticity-posture.md`](../../adr/ADR-0007-package-trust-authenticity-posture.md)
  for the current package trust/authenticity posture;
- [`../../adr/ADR-0008-linked-context-payload-packaging.md`](../../adr/ADR-0008-linked-context-payload-packaging.md)
  for the current package-writer linked-context payload boundary;
- [`../../adr/ADR-0009-batch-receiving-import-planning.md`](../../adr/ADR-0009-batch-receiving-import-planning.md)
  for the current batch receiving/import planning boundary;
- [`../../adr/ADR-0010-selected-record-linked-context-payload-export.md`](../../adr/ADR-0010-selected-record-linked-context-payload-export.md)
  for the current selected-record linked-context payload export boundary;
- [`../../adr/ADR-0011-selected-record-batch-package-export.md`](../../adr/ADR-0011-selected-record-batch-package-export.md)
  for the current selected-record batch export boundary;
- [`../../adr/ADR-0012-defer-linked-context-payload-import.md`](../../adr/ADR-0012-defer-linked-context-payload-import.md)
  for the current durable linked-context payload import deferral;
- [`../../adr/ADR-0013-defer-batch-durable-import.md`](../../adr/ADR-0013-defer-batch-durable-import.md)
  for the current batch durable import deferral;
- [`../../adr/ADR-0014-defer-archive-authority-and-archive-backed-durable-import.md`](../../adr/ADR-0014-defer-archive-authority-and-archive-backed-durable-import.md)
  for the current archive-backed durable import and archive-authority
  deferral;
- [`../../adr/ADR-0015-accept-safe-archive-materialization.md`](../../adr/ADR-0015-accept-safe-archive-materialization.md)
  for the current safe archive materialization boundary;
- [`../../adr/ADR-0016-accept-safe-archive-creation.md`](../../adr/ADR-0016-accept-safe-archive-creation.md)
  for the current safe archive creation boundary;
- [`../../adr/ADR-0017-defer-existing-record-update-and-final-storage-schema.md`](../../adr/ADR-0017-defer-existing-record-update-and-final-storage-schema.md)
  for the current source-storage-read-only export and new-record-only durable
  import boundary;
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
  -> receiving gate
  -> non-mutating import plan
```

The selected stored-record export adapter composes with that package writer:

```text
selected Measurement Record record_id
  -> Measurement Records-owned packageable handoff projection
  -> selected-record export request with explicit declared table-preview metadata
  -> package writer request
  -> directory-shaped selected-measurement package
  -> optional zip transport creation and materialization
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

The package writer is an owner-local capability, not the normal JNY-001 Share
A Selected Measurement entrypoint. Caller-declared package ids, measurement
ids, and linked-context ids are reviewed package-input facts. They are not
durable Scopecat Measurement Record identity and do not replace storage
lifecycle evidence, record-local read models, creation manifests, or writer
receipts.

The selected stored-record export adapter:

- requires an approved selected-record export request;
- selects stored records by `record_id` and delegates canonical lookup,
  read-model freshness, record/receipt continuity checks, and exportability
  classification to Measurement Records;
- preserves projected record id, primary-data path, digest, size, label,
  experiment type, and row count into the package writer request;
- requires explicit declared table-preview metadata and does not infer plot
  semantics from CSV headers;
- can package explicitly declared record-local linked-context payloads under
  `context/` after digest and size preflight;
- writes one package through the package writer: single-measurement for a
  single export request, or multi-measurement for a batch export request that
  selects multiple complete stored records;
- keeps non-declared linked context reference-only and does not treat recorded
  references as payload authority;
- does not parse record-local Measurement Records storage artifacts, mutate
  Measurement Records storage, or own read-model refresh.

Selected-record export receipts keep compact `block_reason` state for blocked
local runs and include the Measurement Records preparation summary. Missing,
invalid, stale, incomplete, or out-of-scope record evidence is classified by
Measurement Records before package writing. Handoff consumes only the typed
packageable projection and package writer facts.

The preflight selected-record export composition makes read-model refresh
user-transparent while keeping ownership explicit. Missing, invalid, or stale
read-model recovery happens inside the Measurement Records preparation route.
The composition does not repair primary data, replace record manifests, mutate
writer/finalization receipts, or accept/import packages.

For JNY-001 Share A Selected Measurement, this storage-backed selected-record
export path is the production vertical slice backbone. Direct package-writer
input remains an adapter or engineering path for already-reviewed normalized
data, not a user-facing bypass around Measurement Records storage.

The current read-only package use:

- validates raw manifest dictionaries at the package boundary;
- uses typed owner-local manifest fragments after validation;
- projects package, measurement, table, finding, and
  linked-context review facts;
- opens package-local primary CSV data for `preview_ready` measurements;
- treats declared table-preview metadata as table-orientation authority only;
- preserves package id and package-directory continuity;
- uses `measurements/{measurement_record_id}/primary.csv` as the canonical
  primary-data package topology.

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

Receiving gate and import-plan receipts keep compact `block_reason` state for
blocked local runs. That state reflects integrity-review blocks and
receiving-gate readiness before durable import is considered. It does not
authorize retry, package acceptance, or storage mutation.

Public receiving and import-planning API functions promote route contract
failures to `HandoffContractError`, which remains `ValueError`-compatible.
`to_diagnostic()` exposes a local operator diagnostic with operation, code, and
message. That diagnostic is a local review surface only; it is not a
portable/export artifact, retry authorization, package acceptance, storage
mutation authority, or public error schema.

## Artifact Authority

The package directory and `package-manifest.json` are portable handoff
artifacts. Package contents must use package-relative paths and validated
managed references at the package/export boundary.

[`ADR-0006`](../../adr/ADR-0006-package-format-directory-manifest.md) keeps this
directory manifest package as the current JNY-001 Share A Selected Measurement
production vertical slice package format. Archive bytes are transport
containers; the materialized directory package remains the package of record.

[`ADR-0014`](../../adr/ADR-0014-defer-archive-authority-and-archive-backed-durable-import.md)
kept archive implementation deferred until archive artifact authority,
extraction safety, staging, and materialization review contracts existed.
[`ADR-0015`](../../adr/ADR-0015-accept-safe-archive-materialization.md)
accepts a narrow zip materialization candidate.
`materialize_handoff_archive_package_from_request()` materializes a zip
transport archive into a ADR-0006 directory-manifest package after path,
duplicate-member, symlink, metadata-member, manifest, collision, cleanup, and
package-open checks.
[`ADR-0016`](../../adr/ADR-0016-accept-safe-archive-creation.md)
accepts `create_handoff_archive_package_from_request()` for creating zip
transport archives from openable ADR-0006 packages under no-overwrite.
Signature/trust validation and archive-backed durable import remain out of
scope.

[`ADR-0007`](../../adr/ADR-0007-package-trust-authenticity-posture.md)
keeps this package as declared-integrity local-review evidence. Declared digest
integrity may gate receiving/import planning, but external authenticity, sender
trust, and scientific validity remain unclaimed.

Local writer receipts, workflow receipts, receiving-gate results, and
import-plan objects are local review surfaces unless a later slice explicitly
promotes one as a portable/export artifact.

Selected stored Measurement Record export may package request-declared
record-local linked-context payloads under `context/`. The package-use route
may expose linked-context references for review, but it does not recursively
traverse references, restore environments, or import linked context into
durable Measurement Records storage.

[`ADR-0008`](../../adr/ADR-0008-linked-context-payload-packaging.md)
narrows that posture for the generic package writer: explicitly declared
linked-context payload files may be packaged under `context/`, opened as
`packaged_payload`, and integrity-observed. Import planning and durable import
still do not import linked-context payloads.

[`ADR-0010`](../../adr/ADR-0010-selected-record-linked-context-payload-export.md)
extends that posture to selected stored Measurement Record export only when the
export request explicitly declares a record-local source path, `context/`
package path, digest, and byte size. Recorded linked references remain
reference-only review facts unless the request carries that payload authority.

[`ADR-0009`](../../adr/ADR-0009-batch-receiving-import-planning.md)
allows non-mutating import plans to list multiple package measurements. Durable
handoff import remains one planned measurement per storage mutation.

[`ADR-0012`](../../adr/ADR-0012-defer-linked-context-payload-import.md)
keeps linked-context payload import deferred. Packaged linked context remains
reviewable package content; import planning keeps `keep_reference_only` and
durable import does not materialize linked payloads into Measurement Records
storage.

[`ADR-0013`](../../adr/ADR-0013-defer-batch-durable-import.md)
keeps batch durable import deferred. Multi-measurement packages may be reviewed
and planned together, but durable import remains one planned measurement per
storage mutation.

[`ADR-0017`](../../adr/ADR-0017-defer-existing-record-update-and-final-storage-schema.md)
keeps selected stored-record export source-storage-read-only and receiving
durable import new-record-only. Existing-record update, merge import, manifest
replacement, primary-data compaction, post-run results review, and final storage
schema publication remain outside the current JNY-001 production readiness
boundary.

## Production Vertical Slice

JNY-001 Share A Selected Measurement has a production vertical slice smoke path
when one workflow-level regression proves this full path:

```text
source-side durable Measurement Record
  -> selected stored-record package export
  -> safe zip archive creation from the ADR-0006 package of record
  -> safe zip archive materialization back into the ADR-0006 package of record
  -> read-only receiving package open
  -> receiving gate
  -> non-mutating import plan
  -> durable import into a second storage root
```

Acceptance for that slice is intentionally narrow:

- exactly one selected, complete Measurement Record is exported;
- primary CSV bytes, digest, size, label, experiment type, and record identity
  remain continuous through export and receiving;
- preview metadata is explicit and package-manifest authored;
- stale or missing source-side record evidence blocks export before producing a
  new package;
- existing package destinations use no-overwrite behavior;
- blocked selected-record exports expose compact block reasons without
  authorizing retry;
- corrupted package bytes block receiving/import through integrity review;
- blocked receiving and import planning expose compact block reasons without
  authorizing retry;
- declared digest integrity remains separate from external authenticity, sender
  trust, and scientific validity;
- receiving review facts must match the opened package and observed integrity;
- blocked durable imports expose block reasons without authorizing mutation;
- receiving review and import planning remain non-mutating;
- durable storage mutation remains delegated to Measurement Records import;
- durable import receipts expose block reasons without authorizing mutation;
- local receipts remain review surfaces, not portable package artifacts;
- selected stored Measurement Record export may package explicitly declared
  record-local linked-context payloads, while durable import keeps linked
  context reference-only;
- source-side selected-record export remains read-only over Measurement Records
  storage, and receiving durable import creates a new record rather than
  updating an existing one.

This slice is not production readiness for the whole handoff capability.
Persisted GUI/review state, public SDK contracts, and final storage schemas
remain separate decisions. Zip transport archive materialization into the
ADR-0006 directory package of record is governed by
[`ADR-0015`](../../adr/ADR-0015-accept-safe-archive-materialization.md),
while archive creation is governed by
[`ADR-0016`](../../adr/ADR-0016-accept-safe-archive-creation.md).
Archive-backed durable import and broader archive semantics remain outside this
boundary.
Generic writer linked-context payload packaging without import is governed by
[`ADR-0008`](../../adr/ADR-0008-linked-context-payload-packaging.md).
Batch import planning without batch durable mutation is governed by
[`ADR-0009`](../../adr/ADR-0009-batch-receiving-import-planning.md).
Selected-record linked-context payload export is governed by
[`ADR-0010`](../../adr/ADR-0010-selected-record-linked-context-payload-export.md).
Selected-record batch export without batch durable import is governed by
[`ADR-0011`](../../adr/ADR-0011-selected-record-batch-package-export.md).
Linked-context payload import deferral is governed by
[`ADR-0012`](../../adr/ADR-0012-defer-linked-context-payload-import.md).
Batch durable import deferral is governed by
[`ADR-0013`](../../adr/ADR-0013-defer-batch-durable-import.md).
Archive-backed durable import and archive-authority deferral are governed by
[`ADR-0014`](../../adr/ADR-0014-defer-archive-authority-and-archive-backed-durable-import.md).
Safe zip archive materialization is governed by
[`ADR-0015`](../../adr/ADR-0015-accept-safe-archive-materialization.md).
Safe zip archive creation is governed by
[`ADR-0016`](../../adr/ADR-0016-accept-safe-archive-creation.md).
Existing-record update and final storage schema deferral for this handoff slice
are governed by
[`ADR-0017`](../../adr/ADR-0017-defer-existing-record-update-and-final-storage-schema.md).

## Historical Context

Discovery candidates and the older
`measurement_record_directory_candidate_v0` storage-acceptance route remain
historical evidence only. They are useful for review order, approval, receipt,
and rollback pressure, but they are not live runtime dependencies, no longer
exist as installable `src` modules, and should not be extended as the durable
Measurement Records import path.

The detailed historical notes were removed from active docs and are indexed in
[`../archive/README.md`](../archive/README.md). Recover narrow facts from Git
history only when current handoff or Measurement Records owners need them.

## Out Of Scope

This boundary does not accept:

- final public SDK names or package publishing metadata;
- hard pandas/numpy dependency;
- production plotting or publication-grade rendering;
- live GUI components, routing, interaction model, or GUI-owned persisted
  review state;
- numeric dtype conversion, unit conversion, schema inference, scan-shape
  inference, trace opening, or array API;
- archive-backed durable import or compressed package format beyond ADR-0015 and
  ADR-0016;
- external authenticity validation or trusted-source policy;
- package acceptance, existing-record update or merge import beyond ADR-0017,
  durable multi-measurement batch import beyond ADR-0013, rollback policy, or
  storage conflict policy;
- recursive traversal or linked-context payload import beyond ADR-0012;
- analysis/fit result model, fit execution, uncertainty, write-back, or result
  import;
- shared measurement-record domain model or cross-route object lifecycle.

## Tests And Fixtures

Active prototype tests live under
[`../../../tests/prototypes/handoff/`](../../../tests/prototypes/handoff/).
Handoff fixtures live under
[`../../../tests/fixtures/prototypes/handoff/`](../../../tests/fixtures/prototypes/handoff/).

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
- existing-record update/import or final storage schema beyond ADR-0017;
- GUI-owned persisted receiving review state;
- archive-backed durable import or broader archive semantics beyond ADR-0015 and
  ADR-0016;
- durable linked-context payload import beyond ADR-0012 or batch durable import
  beyond ADR-0013;
- analysis or fit results as first-class package display facts;
- shared lifecycle or domain model extraction justified by more than one
  accepted route.
