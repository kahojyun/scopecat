# Measurement Records Prototype Boundary

## Status

Accepted engineering-prototype boundary.

This file owns the current durable Measurement Records prototype boundary. The
filename is historical: the first accepted slice was record creation, but the
live boundary now includes the owner-local storage, import, and reference
surfaces listed below plus internal primary-table reads used for composition.
Keep public entrypoint
orientation in
[`../../../src/scopecat/measurement_records/README.md`](../../../src/scopecat/measurement_records/README.md).

## Current Boundary

The prototype validates caller-rooted local Measurement Records storage:

```text
approved request
  -> caller-provided storage root
  -> record-local manifest, receipts, primary data, or read model
  -> no-overwrite or read-only behavior appropriate to the operation
  -> local result
```

Accepted surface groups:

| Surface | Current Boundary |
| --- | --- |
| Record adoption/import | Creates one no-overwrite record shell with `record-manifest.json` as part of a durable import or legacy-run adoption operation. |
| JNY-007 basic UX | Provides an adoption facade that builds canonical record-local paths and returns a stable local record handle for adopt-first and import-ready routes. |
| Record open-by-id | Opens one canonical record from `record_id`, returning user-shaped record, source-locator, primary-data, and reference-set summaries without scanning, parsing, or refreshing. |
| Primary-data attach flow | Writes reviewed normalized primary CSV, finalization receipt, and `record-read-model.json` for legacy attach paths. |
| Durable import | Imports one reviewed normalized primary table directly into a new record with synchronous partial-failure rollback. |
| Recorded references | Writes record-local receipts for user-declared context references while leaving referenced payloads outside Measurement Records ownership. |

Stored primary-table reads are internal composition helpers for the attach,
import, user-workflow, and selected-record refresh paths. They are not a
separate package-level API or workflow boundary.
The JNY-007 adoption facade and open-by-id view reduce caller exposure to
storage paths, but they do not create a catalog/index, final storage schema,
legacy parser, or post-run browsing surface.

Legacy-run storage and converted-primary attach are owned separately by
[`measurement-records-legacy-run-storage.md`](measurement-records-legacy-run-storage.md).
Handoff durable import composition is owned by
[`handoff-durable-import-storage.md`](handoff-durable-import-storage.md).

## Artifact Boundary

Measurement Records storage is local, caller-rooted durable storage. Current
record-local artifacts are:

- `record-manifest.json` as the immutable creation shell and origin identity;
- record-local receipts for writer, finalization, import, legacy-run recording,
  and references;
- primary CSV bytes written through approved writer/import paths;
- derived `record-read-model.json` as a replaceable local convenience
  summary, not canonical storage authority.

## Storage Authority

Current authority model:

- import/adoption operations own initial manifest creation;
- import/attach operations own primary CSV bytes and their receipts;
- selected-record export refresh owns derived read models, not canonical
  manifest replacement.

The prototype keeps manifest replacement, existing-record merge import, broad
conflict resolution, stale-lock cleanup, crash recovery, and concurrent storage
mutation outside the current boundary.
For JNY-001 Share A Selected Measurement production readiness, ADR-0017 keeps
selected-record export source-storage-read-only and handoff durable import
new-record-only; it does not promote existing-record merge import, completed
record finalization, manifest replacement, or final public storage schema
publication.

## Tests And Fixtures

The active prototype tests live under
[`../../../tests/prototypes/measurement_records/`](../../../tests/prototypes/measurement_records/).
Relevant fixture families live under
[`../../../tests/fixtures/prototypes/measurement_records/`](../../../tests/fixtures/prototypes/measurement_records/).
The active Measurement Records tests currently use `durable_import/`.

The retained scan/data-shape discovery fixtures live separately under
[`../../../tests/fixtures/scan_data_shapes/`](../../../tests/fixtures/scan_data_shapes/).

Run repository checks with:

```sh
uv run python -m unittest discover -s tests
uv run ruff check .
uv run ruff format --check .
```

## Advancement Questions

Do not expand this prototype by appending more historical checkpoints to this
file. Create or update a narrower boundary note when a workflow needs one of:

- selected stored Measurement Record to single-measurement handoff package
  export;
- existing-record merge import or manifest replacement beyond ADR-0017;
- stronger storage recovery, locking, or concurrency behavior;
- durable running-monitor decisions such as saved selections, saved fit
  results, or GUI state persistence;
- referenced payload import, relation traversal, or final cross-route domain
  model extraction.
