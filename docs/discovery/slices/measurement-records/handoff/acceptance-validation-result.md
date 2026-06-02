# Handoff Package Acceptance Validation Result

## Status

Implementation candidate validated.

Document role: historical discovery validation result. It records what this
slice earned and what it did not establish. Later engineering implementation
decisions are owned by
[`handoff-candidate-storage-acceptance.md`](../../../../architecture/archive/handoff-candidate-storage-acceptance.md)
and the current durable handoff import route is owned by
[`handoff-durable-import-storage.md`](../../../../architecture/boundaries/handoff-durable-import-storage.md);
do not update this result to mirror live API or receipt changes.

This result validates the old first approved receiving-side candidate storage
mutation
intended to run after read-only review of a directory-shaped handoff package.
It verifies approval plus reviewed package identity/classification; it does
not bind to an inspection receipt. It is not accepted architecture, a final
import API, final storage layout, archive format, dataframe adapter, GUI
workflow, package-integrity verifier, or shared measurement-record model.
It is not the active durable Measurement Records handoff import route.

## Fixture

Fixture:
[`../../tests/fixtures/handoff_package_opener/basic_package/package/handoff-package-legacy-rabi-001/`](../../../../../tests/fixtures/handoff_package_opener/basic_package/package/handoff-package-legacy-rabi-001)

Implementation candidate:
[`../../implementation_candidates/handoff_package_acceptance/`](../../../../../implementation_candidates/handoff_package_acceptance)

The candidate reuses the already openable handoff-package fixture and adds an
explicit acceptance request in tests. This keeps approval and destination
intent visible rather than deriving a storage mutation from an inspection
summary.

## What This Earned

The candidate shows that a reviewed handoff package can be accepted into local
storage through a small, explicit mutation boundary:

- require `scopecat.handoff_package_acceptance.v0` input and an exact
  acceptance policy posture;
- reopen the package through the read-only handoff package read view;
- require `approval_state: approved`;
- require reviewed package id and reviewed preview classification to match the
  opened package;
- require the acceptance request to select every package measurement;
- require generated local record paths of the form
  `records/{measurement_record_id}/primary.csv` and
  `records/{measurement_record_id}/record-manifest.json`;
- refuse existing record directories and storage targets with ordinary
  no-overwrite behavior under a non-concurrent storage-root assumption;
- copy package-local primary CSV bytes into local storage;
- write deterministic candidate-local record manifests beside the copied data;
- preserve linked context as reference-only manifest facts;
- roll back ordinary partial writes when a later write fails.

Artifact posture: `local_write_receipt`. The receipt and candidate-local
record manifest are local storage/review artifacts, not portable package
members, public reports, or shared storage manifests.

## Boundary

This candidate deliberately keeps acceptance narrower than a product importer.
It does not:

- infer acceptance from a visual inspection receipt;
- import degraded-preview packages;
- update existing records;
- recursively import linked-context payloads;
- extract archives or accept archive paths;
- validate package-declared checksums, signatures, or package integrity;
- support concurrent package-root modification during acceptance;
- support concurrent storage-root modification during acceptance;
- infer schemas, scalar types, dataframe behavior, or plotting behavior;
- define a live GUI flow, stable SDK method names, final storage schema, or
  shared measurement-record domain model.

The copied primary-data digest and size in the local record manifest are facts
about the bytes copied into storage. They are not claims that the source
package's declared integrity metadata was verified.

This result owns only the acceptance boundary, reviewed package continuity
checks, new-record-directory requirement, and local manifest shape validated by
the discovery slice. It does not establish race-safe no-overwrite semantics,
locks, atomic publish behavior, or crash recovery.

## Result

At this checkpoint, the handoff package route had separate validated steps for:

- producing a directory package;
- opening and reviewing it read-only;
- composing a local inspection workflow;
- accepting the reviewed package into local storage through an explicit
  approved mutation.

This gave the route a complete prototype loop while preserving the main
engineering boundary: inspection remained read-only; acceptance was the first
receiving-side write; and final importer, GUI, storage architecture, archive,
integrity, concurrent package/storage handling, dataframe, and shared-schema
decisions remained separate.
