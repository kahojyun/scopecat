# Durable Import Storage Decision

## Status

Accepted engineering-prototype boundary.

This note chooses the first durable storage/import boundary after Measurement
Records gained durable creation, writer attachment, read view, finalization,
read-model projection, catalog, refresh, and an explicit decision against
manifest replacement. It supersedes the waiting posture in
[`handoff-storage-import-requirements-synthesis.md`](../archive/handoff-storage-import-requirements-synthesis.md)
for the narrow question of what durable import can implement first.

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
[`../../../src/scopecat/measurement_records/`](../../../src/scopecat/measurement_records/).
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
row-count blocking before mutation, read-view rollback, finalization rollback,
and projection-failure rollback.

It deliberately does not import into an existing record, attach to an existing
created shell, merge primary data, replace manifests, import linked-context
payloads, define adapter transport/discovery, or add conflict policy beyond
new-record no-overwrite behavior.

## Handoff Package Integration Decision

Use the ready handoff import plan as the only handoff-side input boundary for
durable import source facts.

The next slice should prove:

```text
open handoff package
  -> observe package integrity
  -> approved receiving gate
  -> ready non-mutating import plan
  -> caller-declared durable record destination
  -> MeasurementRecordImportSource
  -> MeasurementRecordDurableImportRequest
```

The handoff package route should not call the older candidate storage
acceptance path when the target is durable Measurement Records storage. It
should adapt one ready import-plan measurement into the already implemented
durable import request shape, then let the Measurement Records durable import
pipeline perform creation, primary-data writing, read view, finalization, and
read-model projection.

For the first implementation, support exactly one selected package
measurement. Multi-measurement packages should remain representable in the
read-only import plan, but durable import should require a caller to choose one
measurement and one destination record per operation. Batch import needs its
own rollback and partial-success decision.

## Handoff Fact Mapping

The adapter from handoff package review to durable import should map:

| Durable import field | Handoff source |
| --- | --- |
| `source_kind` | `handoff_package` |
| `source_id` | opened package id |
| `source_item_id` | package measurement record id |
| `content_ref` | measurement primary package path |
| `declared_digest` | measurement declared primary-data digest after integrity observation |
| `size_bytes` | measurement observed primary-data byte size, requiring agreement with declared size when present |
| `rows_recorded` | opened primary table row count |
| `primary_data_format` | measurement primary format, currently `csv_table` |
| `label` and `experiment_type` | package measurement label and experiment type |
| `creation_source_kind` | `handoff` |

Package integrity remains a precondition. It may be referenced in the local
adapter receipt, but it does not become signature, authenticity, trust, or
archive validation. Linked context remains reference-only review context. The
first adapter should not copy linked-context payloads into storage or encode
them into the durable import source facts beyond non-claim summaries.

## First Handoff Integration Contract

The first handoff integration implementation should:

- require a ready `HandoffImportPlanRun`;
- require exactly one planned measurement import;
- require a caller-declared durable destination: `record_id`, `record_dir`,
  `primary_data_path`, `writer_receipt_path`, `finalization_receipt_path`, and
  `read_model_path`;
- verify the selected measurement still belongs to the package and import
  plan;
- reject package measurements without declared digest or size facts;
- construct `MeasurementRecordImportSource` and
  `MeasurementRecordDurableImportRequest`;
- optionally call `import_measurement_record_from_request(...)` when the
  caller asks for a composed operation;
- preserve no-overwrite and rollback behavior inside the durable import
  pipeline rather than reimplementing storage mutation in the handoff module;
- return a local handoff integration receipt that reports package id,
  measurement id, destination facts, durable import classification, and
  explicit non-claims.

This handoff integration does not accept:

- multiple-measurement durable batch import;
- importing into existing records or attaching to pre-created shells;
- using `measurement_record_directory_candidate_v0`;
- linked-context payload materialization;
- archive extraction, signatures, authenticity, or trust policy;
- adapter transport/discovery or stable public adapter API;
- conflict policy beyond the durable import new-record no-overwrite behavior;
- GUI import review state or durable cross-session operator decisions.

## Handoff Integration Implementation Checkpoint

The first handoff-to-durable adapter is implemented in
`scopecat.handoff.durable_import`.

It exposes:

- `HandoffDurableImportDestination` for the caller-declared durable record
  paths;
- `HandoffDurableImportRequest` for the package id, selected package
  measurement id, approval state, and destination;
- `build_durable_import_request_from_handoff_plan(...)` for the read-only
  mapping into `MeasurementRecordDurableImportRequest`;
- `run_handoff_durable_import_from_plan(...)` for typed composition from a
  ready import plan;
- `run_handoff_durable_import(...)` for the raw edge that runs the import plan
  and then delegates to durable import.

The adapter blocks before durable mutation when the import plan is not ready or
the handoff durable import request is not approved. When it proceeds, it
requires exactly one planned measurement, requires the requested measurement id
to match that plan, requires declared digest and size facts, verifies observed
and declared primary-data size agreement, maps the package primary-data facts
to `MeasurementRecordImportSource(source_kind="handoff_package")`, and calls
`import_measurement_record_from_request(...)` with the package directory as the
content root. The delegated Measurement Records durable import pipeline then
re-opens the package member and preflights digest, byte size, normalized CSV
shape, and row count before durable storage mutation, so a stale ready handoff
plan does not by itself authorize writing changed package bytes.

Tests cover successful import, raw-edge composition, blocked-plan no-mutation
behavior, stale-package source revalidation before mutation, and package-id
mismatch validation. The adapter continues to leave no-overwrite, rollback,
finalization, and read-model projection semantics to the Measurement Records
durable import pipeline.

## Handoff Durable Receipt Summary Checkpoint

The route now also includes
`summarize_handoff_durable_import_receipt(...)` for read-only operator
continuation summaries.

The summary records:

- package id;
- selected package measurement id;
- destination durable record id;
- final handoff durable-import state;
- next local operator action;
- durable import classification and whether durable mutation completed;
- rollback, partial-commit, and import-error flags when present.

This summary is intentionally not continuation authority. It does not approve a
retry, reuse a prior import plan, prove destination freshness, reopen the
package, or mutate storage. A retry or follow-up import still needs a fresh
handoff durable import request and the same ready-plan/durable-import checks.

## Handoff Durable Retry Review Checkpoint

The route now includes `review_handoff_durable_import_retry(...)` as a
read-only retry review over a previous handoff durable import receipt summary
and a fresh `HandoffImportPlanRun`.

The retry review:

- validates package identity against the fresh import plan;
- validates selected measurement identity when the fresh plan is ready;
- reports successful prior imports as not retryable;
- blocks retry after partial-commit outcomes until that state is reviewed;
- reports a fresh ready single-measurement import plan as retry-ready;
- reports blocked fresh plans without authorizing mutation.

It deliberately does not create a durable import request, reuse the prior
receipt or import plan as authority, prove destination freshness, approve
storage mutation, or persist durable GUI review state. A retry still requires a
fresh handoff durable import request with caller-declared destination facts.

## Reference-Only Experiment Context Checkpoint

The handoff route now preserves optional managed context-reference metadata on
reference-only linked context entries. This is the first narrow implementation
slice for experiment-context package continuity:

```text
package writer linked_context.context_reference
  -> package manifest reference-only context entry
  -> read-only package open
  -> non-mutating import plan linked-context projection
  -> handoff durable-import local receipt
```

The `context_reference` object is intentionally small: public-safe
`reference_id`, `reference_kind`, `reference_family`, and explicit
`materialization: reference_only` plus `payload_import: not_performed`.
The writer and manifest preview validate those managed reference fields, require
`reference_kind` to match the linked-context `kind`, and reject payload-import
claims. The opener and import plan carry the reference forward for review, and
the handoff durable-import receipt includes the linked-context import-plan
projection so operators can see which context references stayed outside the
durable import payload.

The route also exposes `summarize_package_context_references(...)` as a
read-only local review summary over an opened package. It reports context
reference counts, family counts, managed reference entries, and linked-context
ids that do not yet carry managed reference metadata. The summary is useful for
receiving-side orientation before import planning or durable import, but it is
not continuation authority and does not become a public package schema.
The `prepared_run` reference family is narrowed to `prepared_run_context`
references and the summary exposes selected prepared-run context ids directly.
This keeps manual run-preparation continuity visible while preserving the
prepared-run route's existing non-claims around restore, readiness, execution,
environment sync, and GUI state.

This checkpoint does not package experiment code, prepared-run payloads,
environment files, parameter payloads, or setup payloads. It does not resolve
references, restore environments, import linked context into Measurement
Records storage, broaden durable import source facts, create a public package
schema, or define GUI review state.

## Current Trigger Closure

The durable/final local-record trigger is satisfied for the current scoped
workflow:

```text
reviewed handoff package
  -> ready single-measurement import plan
  -> caller-declared new durable record destination
  -> Measurement Records durable new-record import
  -> local receipt summary and retry review
```

The implemented boundary covers one package measurement imported as one new
Measurement Records record with no-overwrite behavior, finalization, read-model
projection, local handoff receipt summary, local retry review, and CLI receipt
summary support.

Further work in this area should open a separate decision and name the missing
user workflow. In particular, existing-record update, attach-to-created-shell,
multi-measurement batch import, conflict handling beyond no-overwrite, stronger
recovery/concurrency semantics, linked-context payload import, package
trust/archive behavior, public adapter transport, and GUI durable review state
remain outside the current trigger.
