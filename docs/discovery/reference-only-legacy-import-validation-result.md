# Reference-Only Legacy Import Validation Result

## Status

Implementation candidate validated.

This result validates a narrow Measurement Records slice:
**Reference-Only Legacy Import**.

It does not accept a stable public adapter or import API, LabRAD, DataVault,
or Labber reader, primary-data copy, storage mutation, source observation,
reference repair, Scopecat export-package acceptance flow, linked-context
payload import, schema inference engine, recursive relation traversal,
package integrity contract, or GUI workflow.

## Fixture

Fixture:
[`../../tests/fixtures/reference_only_legacy_import/basic_reference/`](../../tests/fixtures/reference_only_legacy_import/basic_reference/)

Implementation candidate:
[`../../implementation_candidates/reference_only_legacy_import/`](../../implementation_candidates/reference_only_legacy_import/)

The fixture starts after a user-owned adapter has emitted a normalized
adapter-authored manifest and an import review has approved a reference-only
acceptance request. For the boundary between external source references and
Scopecat-readable primary data, see
[`measurement-data-reference-boundary.md`](measurement-data-reference-boundary.md).
The request includes:

- the full adapter-authored manifest;
- an explicit approved reference-only request;
- a lab-managed shared-storage current reference with public-safe redacted
  display facts;
- an explicit materialization policy that keeps primary data external,
  preserves source identity, and keeps linked context reference-only.

The candidate validates the embedded adapter manifest with the existing
adapter-authored legacy import candidate, checks that the reviewed manifest
classification is ready for review, validates the public-safe current
reference facts, reports source openability, size, digest, and schema
verification as unobserved, and reports copying and storage mutation as not
performed.

## What This Earned

The implementation candidate shows that Scopecat can represent the
reference-only side of legacy import acceptance without taking storage or
source-observation authority:

- require an approved reference-only request;
- reuse the normalized manifest boundary instead of parsing legacy formats in
  core;
- preserve adapter identity, external source identity, declared preview
  metadata, and linked-context references;
- validate that current-reference labels and display paths remain public-safe
  and redacted;
- keep the current external source reference adapter-declared and unobserved;
- explicitly report copy and storage mutation as not performed;
- keep Scopecat-authored export or handoff package acceptance separate.

## Boundary

This slice validates a side-effect-free reference-only acceptance summary.

It does not:

- parse LabRAD, DataVault, Labber, or lab-specific legacy records in Scopecat
  core;
- define a stable public adapter API, SDK, command-line interface, or import
  package format;
- copy primary data, write storage, write manifests, or update records;
- open, checksum, size, repair, or verify the external source reference;
- plot, preview, expose dataframe-like rows, or otherwise claim Scopecat
  understands the external source reference; a later data-level open/read
  slice must validate normalized data access before those surfaces are enabled;
- accept Scopecat-authored export or handoff packages;
- import linked-context payloads or traverse relations recursively;
- infer schema, preview metadata, plot candidates, units, or scientific
  validity from source data;
- define final measurement storage architecture, manifest schema, or package
  integrity semantics;
- control hardware, run scans, mutate parameters, or define GUI behavior.

## Result

Reference-only legacy import complements the copy-into-new-record acceptance
slice. It validates that a lab can preserve a known shared-storage location as
the current external source reference when copying is not desired or not yet
approved, while keeping the source unobserved unless a later file-level
source-observation slice explicitly checks it.

This keeps the copy/reference decision explicit. Copying primary data,
observing the external reference, repairing moved references, accepting
adapter packages, or updating existing records remain separate validation
questions.

## Follow-Up

Stop this slice at side-effect-free reference-only acceptance unless the next
workflow needs a harder storage or adapter boundary.

Likely follow-up slices should stay separate:

- file-level source observation for reference-only imported records is now
  validated separately in
  [`reference-only-source-observation-validation-result.md`](reference-only-source-observation-validation-result.md);
- existing-record append or update pressure, including locks and crash
  recovery;
- final adapter handoff transport, discovery, and trust beyond the current
  adapter output boundary;
- reference repair or moved-reference review without automatic path discovery;
- harder adapter-authored data-shape cases, such as ragged scans or
  trace-per-point data, without automatic schema inference.
