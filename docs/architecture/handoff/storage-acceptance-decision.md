# Handoff Storage Acceptance Slice Decision

## Status

Engineering decision for the first handoff storage-acceptance implementation
slice, not an ADR.

This note chooses the next implementation boundary after
[`run_acceptance_preflight(...)`](../../../scopecat/handoff/README.md). It is
the owner for first-mutation slice scope, rollback expectations, and
still-deferred storage questions. It is not a broad storage architecture
decision. Keep live API syntax in the handoff module README; keep the broader
accepted handoff boundary in
[`engineering-prototype-promotion-decision.md`](engineering-prototype-promotion-decision.md).

Artifact posture: `internal_validation_summary`. This note creates no
portable package output, public contract, public SDK, or new redaction rule.

## Decision

Choose the first package receiving/import mutation implementation candidate as
a narrow storage acceptance operation:

```text
ready acceptance preflight
  -> approved storage acceptance request
  -> copy package primary data to one declared record directory
  -> write one record manifest
  -> return local acceptance receipt
```

The only storage shape in scope for this first implementation slice is
`measurement_record_directory_candidate_v0`. It is a route-local candidate
layout for this mutation, not the final Scopecat storage schema.

The mutation is allowed only after a ready route-local acceptance preflight.
It must preserve the preflight's package id, measurement ids, destination
record ids, relative record directories, primary data paths, manifest paths,
storage schema, observed package root, observed storage root, and
`no_overwrite` collision posture. The mutation request may approve the write;
it may not introduce new destination paths, new selected measurements,
overwrite behavior, linked-context payload import, archive handling, or
storage-schema choices.

## First Mutation Contract

The first implementation should:

- require an approved storage acceptance request;
- consume the route-local `run_acceptance_preflight(...)` boundary, with raw
  request dictionaries parsed only at the public API boundary;
- reject blocked preflight classifications;
- reject destination facts that do not match the preflight exactly;
- reject package or storage roots that do not match the preflight exactly;
- require an existing caller-provided storage root;
- copy each selected package primary data file into its declared
  `primary_data_path`;
- write one `record-manifest.json` at each declared `manifest_path`;
- keep linked context reference-only in the manifest;
- use no-overwrite file creation for every written path;
- return a local receipt that reports performed writes and source package
  continuity.

The first implementation may support only one selected measurement if that
keeps rollback and test evidence small. If it supports multiple measurements,
rollback must cover all files written by the operation, not only one record.

## Rollback Rule

Partial acceptance must not leave a half-accepted record as a successful
result. If any write after the first file fails, the implementation must remove
files it created during the current operation. It may remove now-empty
directories that it created for the current operation. It must not delete
pre-existing files or directories.

The receipt should distinguish:

- `accepted_into_storage` when all declared writes complete;
- `blocked_before_acceptance` when preflight is not ready;
- `rolled_back_after_write_failure` when a write starts but the operation does
  not complete.

Crash recovery, stale cleanup, lock files, transactional filesystem behavior,
and concurrent storage-root mutation are still deferred. This rollback rule is
only best-effort cleanup for synchronous failures observed by the current
process; it is not a durability or crash-recovery guarantee.

## Manifest Scope

The first accepted manifest should be intentionally small. It should carry:

- `schema`: `measurement_record_directory_candidate_v0`;
- destination record id and measurement record id;
- source package id and source package measurement id;
- package-relative source primary data path;
- stored primary data path and format;
- preview metadata copied from the opened package;
- source integrity facts already observed before acceptance;
- linked context entries as reference-only facts;
- explicit non-claims for final storage schema, package authenticity,
  linked-context payload import, schema inference, and scientific validity.

The manifest should not import or rewrite linked-context payloads, infer data
schema from CSV content, compute scientific metadata, or create a shared
measurement-record domain model.

## Out Of Scope

This decision does not accept:

- final storage schema or public storage API;
- existing-record update or merge behavior;
- overwrite, rename, dedupe, or conflict-resolution behavior;
- lock files, stale-lock cleanup, crash recovery, or concurrency semantics;
- package archive extraction, signatures, authenticity, trust policy, or
  adversarial package-root handling;
- linked-context payload materialization;
- dataframe/numeric adapters, schema inference, or scan-shape inference;
- GUI import workflow or interactive review state.

## Next Implementation Check

The first route-local mutation checkpoint is implemented through:

```text
run_acceptance_preflight(...)
  -> run_storage_acceptance(...)
```

It proves successful copy plus manifest write, rejection of blocked or
mismatched preflight facts, package/storage root continuity, no-overwrite
collision behavior, and rollback after a simulated second-write failure.

## Promotion Checkpoint

This slice can be treated as complete for the current branch because it proves
one approved mutation from a ready preflight into one candidate local record
layout. The result is still a candidate storage acceptance receipt, not final
storage architecture.

Do not use this completion as permission to add broader import behavior in
place. Any next storage/import phase should first name the new decision it is
making: user-facing import workflow, final storage/archive requirements,
conflict and existing-record update policy, stronger recovery semantics, or
linked-context payload materialization.
