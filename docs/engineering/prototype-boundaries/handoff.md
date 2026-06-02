# Handoff Package-Use Prototype Boundary

## Status

Accepted engineering-prototype boundary.

## Purpose

This note owns the current package-use boundary for `scopecat.handoff`: writing
Scopecat-authored package directories from caller-declared source files,
opening packages read-only, producing local review surfaces, running receiving
gates, and building non-mutating import plans.

Read it with:

- [`../../../src/scopecat/handoff/README.md`](../../../src/scopecat/handoff/README.md)
  for live API and CLI orientation;
- [`handoff-durable-import-storage.md`](handoff-durable-import-storage.md) for
  the separate durable Measurement Records import adapter boundary;
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

Local writer receipts, workflow receipts, inspection HTML, receiving-gate
results, import-plan objects, CLI summaries, and retry reviews are local review
surfaces unless a later slice explicitly promotes one as a portable/export
artifact.

Linked context is reference-only in this boundary. The package-use route may
expose linked-context references for review, but it does not package linked
payloads, recursively traverse references, restore environments, or import
linked context into durable Measurement Records storage.

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
- archive extraction, compressed package format, signatures, authenticity, or
  trust policy;
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

- selected stored Measurement Record to single-measurement handoff package
  export;
- GUI review beyond local static HTML;
- archive, signature, authenticity, or trust behavior;
- linked-context payload packaging or review;
- analysis or fit results as first-class package display facts;
- shared lifecycle or domain model extraction justified by more than one
  accepted route.
