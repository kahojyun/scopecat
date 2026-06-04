# Measurement Records Prototype Boundary

## Status

Accepted engineering-prototype boundary.

This file owns the current durable Measurement Records prototype boundary. The
filename is historical: the first accepted slice was record creation, but the
live boundary now includes the route-local storage, read, update, import,
reference, and local-review surfaces listed below. Keep public entrypoint
orientation in
[`../../../src/scopecat/measurement_records/README.md`](../../../src/scopecat/measurement_records/README.md).

## Current Boundary

The prototype validates caller-rooted local Measurement Records storage:

```text
approved request
  -> caller-provided storage root
  -> record-local manifest, receipts, primary data, or review artifact
  -> no-overwrite or read-only behavior appropriate to the operation
  -> local result or review summary
```

Accepted surface groups:

| Surface | Current Boundary |
| --- | --- |
| Record creation | Creates one no-overwrite record shell with `record-manifest.json` and a local creation receipt. |
| Primary-data pipeline | Writes reviewed normalized primary CSV, reads it back, finalizes the record, and projects/catalogs/refreshes `record-read-model.json`. |
| Durable import | Imports one reviewed normalized primary table into a new record with synchronous partial-failure rollback. |
| Existing and in-progress updates | Appends explicit update evidence without replacing the creation manifest or merging append segments into canonical primary data. |
| Running inspection | Reads caller-declared in-progress data and update receipts for local progress review without persisting GUI state. |
| Recorded references | Writes record-local receipts for user-declared context references while leaving referenced payloads outside Measurement Records ownership. |
| Operator review | Composes cataloged read models, recorded references, and optional running inspections into read-only local review summaries. |
| Local review artifacts and receipts | Writes local static review HTML and operator-review continuation receipts as caller-rooted review artifacts outside durable record storage authority. |

Legacy-run storage and converted-primary attach are owned separately by
[`measurement-records-legacy-run-storage.md`](measurement-records-legacy-run-storage.md).
Handoff durable import composition is owned by
[`handoff-durable-import-storage.md`](handoff-durable-import-storage.md).

## Artifact Boundary

Measurement Records storage is local, caller-rooted durable storage. Current
record-local artifacts are:

- `record-manifest.json` as the immutable creation shell and origin identity;
- record-local receipts for creation, writer integration, finalization, import,
  legacy-run recording, references, and updates;
- primary CSV bytes written through approved writer/import paths;
- derived `record-read-model.json` as a replaceable local convenience
  projection, not canonical storage authority.

Local review HTML and operator-review continuation receipts are caller-rooted
local review artifacts, not record-local mutation authority. They do not become
portable/export artifacts unless a later workflow explicitly promotes that
boundary.

## Storage Authority

Current authority model:

- record creation owns the initial manifest;
- writer/import operations own primary CSV bytes and their receipts;
- update operations own append receipts and append segments, not primary-data
  compaction;
- read-model projection and refresh own derived read models, not canonical
  manifest replacement;
- review operations own local projections and caller-rooted review artifacts,
  not record mutation authority.

The prototype keeps manifest replacement, existing-record merge import, broad
conflict resolution, stale-lock cleanup, crash recovery, and concurrent storage
mutation outside the current boundary.
For JNY-001 Share A Selected Measurement production readiness, DEC-025 keeps
selected-record export source-storage-read-only and handoff durable import
new-record-only; it does not promote existing-record merge import, completed
record finalization, manifest replacement, or final public storage schema
publication.

## Tests And Fixtures

The active prototype tests live under
[`../../../tests/prototypes/measurement_records/`](../../../tests/prototypes/measurement_records/).
Relevant fixture families live under [`../../../tests/fixtures/`](../../../tests/fixtures/)
and include:

- `normalized_primary_table/`
- `existing_record_update/`
- `running_measurement_inspection/`
- `measurement_record_review_inbox/`
- `measurement_record_handoff_flow/`
- `adapter_authored_legacy_import/`

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
- existing-record merge import or manifest replacement beyond DEC-025;
- stronger storage recovery, locking, or concurrency behavior;
- durable running-monitor decisions such as saved selections, saved fit
  results, or GUI state persistence;
- referenced payload import, relation traversal, or final cross-route domain
  model extraction.
