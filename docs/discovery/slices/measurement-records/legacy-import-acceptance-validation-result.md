# Legacy Import Acceptance Validation Result

## Status

Implementation candidate validated.

Document role: historical discovery validation result. It records the old
copy-into-new-record acceptance candidate for reviewed adapter-authored
manifests. The current durable new-record import boundary is owned by
[`durable-import-storage-decision.md`](../../../architecture/handoff/durable-import-storage-decision.md);
do not update this result to mirror live durable import API or receipt changes.

This result validates an old narrow Measurement Records slice:
**Legacy Import Acceptance**.

It does not accept a stable public adapter or import API, LabRAD, DataVault, or
Labber reader, Scopecat export-package acceptance flow, existing-record update
path, linked-context payload import, schema inference engine, recursive
relation traversal, final storage architecture, package integrity contract, or
GUI workflow.
It is not the active durable Measurement Records new-record import route.

## Fixture

Fixture:
[`../../tests/fixtures/legacy_import_acceptance/basic_acceptance/`](../../../../tests/fixtures/legacy_import_acceptance/basic_acceptance)

Implementation candidate:
[`../../implementation_candidates/legacy_import_acceptance/`](../../../../implementation_candidates/legacy_import_acceptance)

The fixture starts after a user-owned adapter has emitted a normalized
adapter-authored manifest and an import review has approved accepting it. The
acceptance input includes:

- the full adapter-authored manifest;
- an explicit approved acceptance request;
- caller-relative destination paths under a new measurement record directory;
- an adapter-normalized primary-data content reference with declared sha256
  and byte size;
- a materialization policy that copies primary data, preserves external source
  identity, and keeps linked context reference-only.

The candidate validates the embedded adapter manifest with the existing
adapter-authored legacy import candidate, checks that the reviewed manifest
classification is ready for review, preflights the declared primary-data file,
refuses existing targets and symlink parent traversal, copies one primary-data
file, and writes a deterministic imported-record manifest.

## What This Earned

The implementation candidate shows that Scopecat can move from review to a
single bounded acceptance mutation for a normalized adapter-authored legacy
record:

- require an approved acceptance request before storage mutation;
- reuse the normalized manifest boundary instead of parsing legacy formats in
  core;
- validate relative destination paths and no-overwrite behavior;
- preflight adapter-normalized primary-data size and sha256 before writing;
- refuse symlink roots or parent traversal as fixture guardrails;
- write copied normalized primary data and a deterministic manifest under a
  caller-provided storage root;
- preserve adapter identity, external source identity, preview metadata, and
  linked-context references in the stored manifest;
- keep linked context as reference-only instead of recursively importing
  payloads;
- keep Scopecat-authored export or handoff package acceptance separate.

## Boundary

This slice validates one copy-into-new-record acceptance path only.

It does not:

- parse LabRAD, DataVault, Labber, or lab-specific legacy records in Scopecat
  core;
- define a stable public adapter API, SDK, command-line interface, or import
  package format;
- accept Scopecat-authored export or handoff packages;
- append to, merge, overwrite, update, lock, or repair existing records;
- import linked-context payloads or traverse relations recursively;
- infer schema, preview metadata, plot candidates, units, or scientific
  validity from source data;
- define final measurement storage architecture, manifest schema, or package
  integrity semantics;
- control hardware, run scans, mutate parameters, or define GUI behavior.

## Result

Legacy import acceptance was a useful next step after the normalized manifest
slice because it tested the first explicit storage mutation for old lab records
without pulling legacy parsers into Scopecat core. It remains separate from
incoming-record import preview and handoff package contents preview: this
fixture starts from an adapter-authored manifest plus approval, not an
external incoming-record manifest or a Scopecat-authored export package.

For current new-record import, use the durable import decision and prototype
instead. That route creates a Measurement Record through the durable creation,
writer, finalization, read-model, and local receipt pipeline instead of
extending this candidate imported-record manifest shape.

The candidate is intentionally small. It copies one primary-data file and
writes one imported-record manifest under a caller-provided storage root after
digest and size checks. Existing-record append-receipt behavior is validated
separately, and stronger update behavior remains a separate storage problem.

## Follow-Up

Stop this slice at historical copy-into-new-record acceptance unless a future
workflow explicitly needs legacy-specific adapter acceptance pressure not
covered by durable import.

Likely follow-up slices should stay separate:

- stronger existing-record update pressure, including manifest replacement,
  read-model refresh, stale-lock cleanup, crash recovery, and conflict policy;
- final adapter handoff transport, discovery, and trust beyond the current
  adapter output boundary;
- reference-only import planning for lab-managed shared storage without
  copying primary data;
- data-level observation of copied normalized primary data after storage write,
  or separate file-level observation of external source references;
- harder adapter-authored data-shape cases, such as ragged scans or
  trace-per-point data, without automatic schema inference.
