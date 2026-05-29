# Durable Import Storage Decision

## Status

Engineering prototype decision, not an ADR.

This note chooses the first durable storage/import boundary after Measurement
Records gained durable creation, writer attachment, read view, finalization,
read-model projection, catalog, refresh, and an explicit decision against
manifest replacement. It supersedes the waiting posture in
[`storage-import-requirements-synthesis.md`](storage-import-requirements-synthesis.md)
for the narrow question of what durable import can implement first.

Artifact posture: `internal_validation_summary`. This note is internal project
memory. It creates no portable package output, public contract, public SDK, or
new redaction rule. If a future import artifact is exported or published,
classify it under
[`../../discovery/policies/artifact-boundary-and-redaction.md`](../../discovery/policies/artifact-boundary-and-redaction.md)
before adding output fields.

## Decision

Choose new-record durable import through the Measurement Records receipt and
read-model pipeline.

The first implementation slice should prove:

```text
reviewed normalized import source
  -> approved durable import request
  -> create_measurement_record
  -> write_created_record_primary_data
  -> read_created_record_primary_table
  -> finalize_measurement_record
  -> project_measurement_record_read_model
  -> local durable import receipt
```

The imported record is a new measurement record. The first slice should not
attach to a pre-created shell, update an existing record, merge primary data,
extend the old `measurement_record_directory_candidate_v0` handoff layout, or
replace `record-manifest.json`.

## Source Authority

The source must already be reviewed as normalized primary data. The first
durable import operation may consume facts from a handoff package review,
adapter-produced boundary, or route-local test fixture only after the source
declares:

- source kind, such as `handoff_package` or `adapter_normalized_primary_data`;
- source identity and reviewed source item id;
- normalized primary data relative path under a caller-provided content root;
- declared sha256 digest, byte size, row count, and format;
- optional reference-only provenance facts that remain references, not payload
  imports.

Durable import must not parse arbitrary legacy systems, discover package
contents by itself, infer source trust, import linked-context payloads, or turn
external source references into primary data. It consumes reviewed normalized
facts that another route already owns.

## First Implementation Contract

The first implementation should:

- require an approved durable import request;
- require caller-declared `record_id` and `record_dir`;
- require a caller-provided storage root and content root;
- validate source digest, byte size, row count, and format before mutation;
- create exactly one new record shell using the existing creation operation
  with creation source kind `import` or `handoff`;
- write exactly one normalized primary data file and writer receipt using the
  existing writer-integration operation;
- read the stored primary table through the existing read-view operation;
- write `finalization-receipt.json` as `complete` only when the read view is
  ready and row-count evidence agrees;
- write `record-read-model.json` through the existing projection operation;
- return a local durable import receipt that links the source facts and each
  route-local run receipt classification;
- preserve no-overwrite conflict behavior for the new record directory and
  record-local files;
- best-effort roll back files and empty directories created by the current
  import if a synchronous failure occurs before final projection completes.

The implementation may use one normalized CSV primary-data file as one writer
chunk for the first slice. That is an import adapter into the existing
writer-integration contract, not a new primary-data merge model.

## Failure And Rollback Scope

The first slice should classify failures as:

| Classification | Meaning |
| --- | --- |
| `imported_new_record` | Creation, writer integration, read view, finalization, and projection all completed. |
| `blocked_before_import` | Approval, source facts, destination facts, or preflight validation blocked before storage mutation. |
| `rolled_back_after_import_failure` | Storage mutation started, but the operation failed before final projection and best-effort cleanup ran. |
| `import_failed_after_partial_commit` | A later synchronous failure occurred after a step whose existing contract cannot be safely undone by this import wrapper. |

Rollback remains best-effort process-local cleanup. It is not crash recovery,
transactional durability, stale-lock cleanup, or concurrent storage-root
protection. If the first implementation cannot safely roll back after a
particular existing operation, it must report the partial-commit classification
rather than hide the condition.

## Out Of Scope

This decision does not accept:

- import into an existing record;
- attach-to-existing-created-shell workflow;
- primary-data merge, compaction, or append visibility as canonical primary
  data;
- final record-id generation policy;
- manifest replacement or canonical-current-state manifest updates;
- linked-context payload materialization;
- archive extraction, signatures, authenticity, or package trust policy;
- adapter discovery, drop-folder protocol, service API, or stable public
  adapter API;
- conflict policy beyond no-overwrite for a new record;
- lock identity, stale-lock cleanup, crash recovery, or concurrent writer
  behavior;
- public storage schema, export schema, database index, or GUI import review
  state.

## Why Not Candidate Handoff Storage

The older handoff storage-acceptance slice proved one route-local candidate
mutation:

```text
ready acceptance preflight -> approved candidate storage acceptance
```

That layout is still useful evidence, but durable import should not extend it
in place. The Measurement Records pipeline now owns durable creation,
primary-data writing, finalization, and refreshed read models. Reusing that
pipeline keeps authority rules consistent and avoids promoting
`measurement_record_directory_candidate_v0` into a parallel storage schema.

## Next Implementation Stop Condition

Stop the first durable import prototype when tests prove:

- approved normalized import creates one new record and projected read model;
- unapproved import does not mutate storage;
- source digest, size, row-count, or format mismatch blocks before mutation;
- preexisting destination record blocks via no-overwrite behavior;
- read-view or finalization mismatch prevents successful import;
- synchronous post-mutation failure reports rollback or partial-commit status
  explicitly;
- manifests are not replaced and linked-context payloads remain unimported.

After that, choose separate decisions for existing-record import/update,
adapter transport/discovery, handoff package trust/archive behavior, or
stronger recovery semantics.

## Implementation Checkpoint

The first durable new-record import slice is implemented in
[`../../../scopecat/measurement_records/`](../../../scopecat/measurement_records/).
It exposes a raw-dictionary entrypoint, `import_measurement_record(...)`, and a
typed request entrypoint, `import_measurement_record_from_request(...)`.

This slice consumes reviewed normalized primary-data source facts, validates
declared digest, byte size, row count, and format before storage mutation, then
composes the existing Measurement Records operations:

```text
create_measurement_record_from_request
  -> write_created_record_primary_data_from_request
  -> read_created_record_primary_table_from_request
  -> finalize_measurement_record_from_read_view
  -> project_measurement_record_read_model_from_read_view
```

It creates one new record, writes one primary CSV and writer receipt,
finalizes the record as `complete`, projects `record-read-model.json`, and
returns a local durable import receipt with each pipeline step
classification. It proves unapproved no-mutation behavior, source fact
mismatch blocking before mutation, no-overwrite destination blocking,
row-count/finalization rollback, and projection-failure rollback.

It deliberately does not import into an existing record, attach to an existing
created shell, merge primary data, replace manifests, import linked-context
payloads, define adapter transport/discovery, or add conflict policy beyond
new-record no-overwrite behavior.
