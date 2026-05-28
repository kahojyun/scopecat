# Handoff Package Opener Validation Result

## Status

Implementation candidate validated.

This result validates the second receiving-side handoff step after manifest
preview: **read-only handoff package open**.

## Fixture

Fixture:
[`../../tests/fixtures/handoff_package_opener/basic_package/`](../../../../../tests/fixtures/handoff_package_opener/basic_package)

Implementation candidate:
[`../../implementation_candidates/handoff_package_opener/`](../../../../../implementation_candidates/handoff_package_opener)

The fixture represents one directory-shaped Scopecat-authored handoff package:

- `package-manifest.json` at the package root;
- one selected measurement primary CSV at
  `measurements/legacy-rabi-001/primary.csv`;
- one linked context entry preserved as a visible reference-only fact.

## What This Earned

The opener shows that a receiver can use a package without importing it into
local Scopecat storage:

- read and validate the package manifest through the handoff package contents
  preview contract;
- reject empty selected-measurement packages through that shared manifest
  contract;
- require the package directory name to match the manifest `package_id`;
- open package-local primary data through manifest-declared package paths,
  rejecting symlink package roots, primary-data files, and primary-data parent
  directories;
- load UTF-8 CSV rows from declared `csv_table` primary data;
- expose the loaded primary data as a local string-valued table summary with
  unique non-empty headers and rectangular rows for reader-facing wrappers;
- derive preview rows and plot-ready point series from declared preview
  columns and plot candidates;
- preserve manifest-declared `data_shape` as opened summary metadata for
  later declared-shape consumers without inferring shape from CSV contents;
- require `preview_ready` metadata for this first opener candidate; degraded
  preview packages remain manifest-previewable but are not opened for declared
  preview rows until a separate behavior is validated;
- carry manifest-preview findings alongside opener-local findings;
- keep linked context reference-only;
- report declared digest and size facts as manifest facts where present,
  without comparing them or claiming package integrity.

This is the first SDK-shaped package-use candidate. It returns a structured
read model for package contents and declared preview data; it is not a stable
SDK object model or GUI contract.

## Boundary

This candidate is read-only. It does not:

- accept, import, organize, copy, move, archive, or write package contents;
- mutate local Scopecat storage;
- validate package integrity, signatures, checksums, or archive contents;
- extract archives;
- infer schemas from package data;
- recursively traverse linked context or package relations;
- define a final package format, GUI workflow, or stable SDK object model.

## Result

The open-before-import UX now has two validated receiving-side steps:

1. manifest-only package contents preview for quick orientation;
2. read-only package open for immediate package-local primary-data use and
   declared preview plotting.

Package acceptance/import remains a later optional mutation workflow.
Package-integrity or archive validation should stay separate unless a narrower
question shows it is required before safe read-only opening.

Future opener or package-route changes should use
[`routes/measurement-records/handoff/contract-checklist.md`](../../../routes/measurement-records/handoff/contract-checklist.md)
to classify emitted fields before adding validation or output shape.
