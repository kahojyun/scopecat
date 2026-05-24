# Adapter-Authored Legacy Import Validation Result

## Status

Implementation candidate validated.

This result validates a narrow Measurement Records slice:
**Adapter-Authored Legacy Import Manifest**.

It does not accept a stable public API, LabRAD/DataVault/Labber reader,
lab-specific legacy parser in Scopecat core, storage writer, import acceptance
flow, checksum contract, schema inference engine, package format, recursive
relation traversal, GUI workflow, or shared measurement-record schema.

## Fixture

Fixture:
[`../../tests/fixtures/adapter_authored_legacy_import/basic_1d_record/`](../../tests/fixtures/adapter_authored_legacy_import/basic_1d_record/)

Implementation candidate:
[`../../implementation_candidates/adapter_authored_legacy_import/`](../../implementation_candidates/adapter_authored_legacy_import/)

The fixture represents **adapter output**, not legacy input. A user-owned
external adapter has already parsed an old record and emitted a normalized
Scopecat-shaped manifest:

- one adapter identity with explicit external parsing authority;
- one external legacy source identity with public-safe redacted display path;
- one measurement identity;
- one package-relative primary CSV data reference;
- declared 1D preview metadata and row count;
- one adapter-declared parameter-state context reference;
- one adapter finding that says legacy parsing was performed outside
  Scopecat core.

The builder treats the manifest as the authority. It does not open the legacy
source, parse legacy storage formats, infer columns, calculate checksums,
accept the import, write storage, or define a stable SDK or CLI.

## What This Earned

The implementation candidate shows that Scopecat can validate and summarize a
normalized adapter-authored import manifest before committing to a public API
or any core legacy reader:

- keep the manifest schema explicitly versioned as fixture contract
  vocabulary;
- preserve adapter identity, source-system posture, external source identity,
  measurement identity, primary-data reference, preview metadata,
  linked-context references, and adapter findings;
- validate that legacy parsing authority stays outside Scopecat core;
- validate that source display paths remain public-safe and redacted;
- validate package-relative primary-data paths;
- validate declared preview column uniqueness, axis order, and plot candidate
  references;
- classify a complete adapter-authored manifest as ready for import review;
- keep import acceptance and storage mutation explicit non-claims;
- keep LabRAD/DataVault/Labber and lab-specific legacy parsing out of core
  product scope.

## Boundary

This slice validates a normalized artifact boundary only.

It does not:

- parse LabRAD, DataVault, Labber, or lab-specific legacy records in Scopecat
  core;
- define a stable public adapter API, SDK, command-line interface, or package
  format;
- accept, copy, append, archive, checksum, or persist measurement data;
- inspect source files to verify contents, checksums, row counts, or schema;
- infer plot candidates, column roles, units, scan shape, or metadata from
  legacy data;
- define final measurement, lifecycle, progress, storage, import, or
  data-shape schemas;
- traverse linked context recursively or infer analysis DAGs;
- control hardware, run scans, mutate parameters, or make safety decisions.

## Result

Adapter-authored legacy import is a useful bridge between incoming-record
import-preview vocabulary and old lab records without forcing Scopecat to
support old storage formats directly. It is separate from handoff or
export-package contents preview, where the input would be a Scopecat-authored
selected-measurement export package or manifest.

The fixture keeps the engineering boundary simple: legacy-specific knowledge
lives in a user-owned adapter, and Scopecat consumes a normalized manifest with
explicit authority and non-claims. This is enough to test one fixture-local
contract shape that an adapter could emit while avoiding premature API design.

The package-relative CSV is present so the fixture can verify openability and
row-count pressure in tests. The builder itself remains side-effect free and
does not read primary data files.

## Follow-Up

Stop this slice at normalized-manifest validation unless the next workflow
needs import acceptance, storage mutation, or a real adapter integration.

Likely follow-up slices should stay separate:

- import acceptance for an adapter-authored manifest, with explicit storage
  mutation and no-overwrite or copy/reference policy;
- adapter package or drop-folder validation, without accepting a broad package
  format or GUI workflow;
- source observation or checksum validation for adapter-provided primary data,
  without accepting a final integrity contract;
- a local user-owned adapter script example outside Scopecat core, without
  making LabRAD/DataVault/Labber parsing part of core product behavior;
- harder adapter-authored data-shape cases, such as ragged scans or
  trace-per-point data, without automatic schema inference.
