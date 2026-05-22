# Managed Code Version Validation Plan

## Status

Validation plan, not an ADR.

This plan defines the first managed code version record fixture boundary.
It does not accept final managed workspace storage, archive format,
content-addressed store, Git replacement behavior, package management,
environment restoration, selected-version loading, code execution, merge
semantics, workflow/DAG contracts, or GUI design.

## Source Material

This slice follows
[`experiment-code-recording-next-boundary.md`](experiment-code-recording-next-boundary.md).
The prior code-recording slice earned a code snapshot record with an
external root, included files, notebook-output stripping policy, capture-state
posture, and materialization intent. The run/step record defined the snapshot
scope; later selection can choose, promote, or restore that record. It did not
earn storage or restore behavior.

## Validation Question

Can Scopecat represent a first managed code version record for a code snapshot
record while preserving a narrow non-execution boundary?

First fixture:

- `tests/fixtures/managed_code_version/basic_record/`

## Concept Boundary

The first managed-version boundary should distinguish:

| Concept | Meaning In This Plan |
| --- | --- |
| Code snapshot record | The point-in-time code snapshot scope already earned by the prior slice. |
| Managed code version | A Scopecat-assigned record with stable identity, file inventory, integrity hints, and materialization intent. |
| File inventory | The exact included files in the managed record, with recorded form and public-safe metadata. |
| Integrity hint | Lightweight checksum, size, and observation metadata for each file record. This is not a storage backend or restore guarantee. |
| Code capture state | Whether an included source item was content-captured, reference-only, missing, redacted, or excluded before management. Managed versions should not silently upgrade reference-only history into content-comparable inventory. |
| Materialization intent | A declared future workspace materialization target or action. No workspace is created in this slice. |
| Environment restoration | Syncing, loading, dependency checks, and runnable-context validation. Out of scope. |
| Code execution | Importing, loading, running notebooks, or executing recorded files. Out of scope. |

## First Fixture Shape

The first fixture should stay small:

- one code snapshot record from a recorded external code context;
- one managed code version derived from that source record;
- three included file records, including two notebooks recorded without
  outputs and one helper module;
- one Scopecat-assigned stable identity;
- SHA-256, size, and observation-time hints for each file;
- package- or workspace-relative materialization paths;
- attention items for record-only storage, integrity hints, materialization
  not performed, environment not restored, code not executed, and Git not
  inspected.

## Input Boundary

Fixture input may include:

- code snapshot record ID, code context ID, root ID, include list, and
  notebook recording policy;
- managed code version ID, stable identity, status, storage authority, and
  source record reference;
- file records for included paths with role, recorded form, content-state
  hints, and materialization path;
- materialization intent and explicit non-restore, non-environment, and
  non-execution claims.

Fixture input should not include:

- private paths, hostnames, credentials, or raw local user directories;
- unrecorded files, backup folders, caches, checkpoints, or generated files;
- source file contents;
- Git status, branch, commit, remote, diff, merge, push, or pull metadata;
- dependency discovery, environment lockfile syncing, or readiness checks;
- imports, notebook execution, hardware readiness checks, or generated
  artifact regeneration.

## Expected Output

Expected output should let a reviewer answer:

- which code snapshot record became the source;
- which stable managed-version identity was assigned;
- which files are in the managed version;
- which content-integrity hints were recorded;
- which source-record capture assumptions the managed version depends on;
- where files would be materialized if a later slice creates a workspace;
- that storage, archive, restore, environment, loading, execution, and Git
  behavior are not accepted by this fixture.

## Out Of Scope

This plan does not earn:

- final managed workspace storage;
- archive or content-addressed storage;
- Git replacement implementation or internal Git analysis;
- default record-all file tracking;
- package management or environment ownership;
- environment restoration or runnable readiness;
- selected-version loading;
- code execution;
- workflow/DAG or component-level versioning;
- generated artifact regeneration;
- GUI design;
- shared domain model extraction.

## Current Recommendation

Create one fixture and summary candidate before designing a store. The first
goal is to validate the record shape for a managed code version, not to build
the mechanism that captures, restores, or runs one.
