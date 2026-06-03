# Handoff Durable Import Prototype Boundary

## Status

Accepted engineering-prototype boundary.

## Purpose

This note owns the current handoff-to-durable-storage boundary: how one
reviewed handoff package measurement becomes one new durable Measurement
Record.

Read it with:

- [`handoff.md`](handoff.md) for package writing, opening, receiving gates, and
  non-mutating import plans;
- [`measurement-records-creation-lifecycle.md`](measurement-records-creation-lifecycle.md)
  for durable Measurement Records creation, writing, finalization, projection,
  import, and storage authority;
- [`../../../src/scopecat/handoff/README.md`](../../../src/scopecat/handoff/README.md)
  for the live handoff API surface;
- [`../../decisions/architecture/DEC-016-defer-linked-context-payload-import.md`](../../decisions/architecture/DEC-016-defer-linked-context-payload-import.md)
  for the current linked-context payload import deferral;
- [`../../decisions/architecture/DEC-017-defer-batch-durable-import.md`](../../decisions/architecture/DEC-017-defer-batch-durable-import.md)
  for the current batch durable import deferral;
- [`../../decisions/architecture/DEC-018-define-receiving-review-state-contract.md`](../../decisions/architecture/DEC-018-define-receiving-review-state-contract.md)
  for the receiving review state projection boundary;
- [`../../decisions/architecture/DEC-019-defer-package-signature-trust-implementation.md`](../../decisions/architecture/DEC-019-defer-package-signature-trust-implementation.md)
  for the current package signature/trust implementation deferral;
- [`../../decisions/architecture/DEC-020-defer-archive-package-implementation.md`](../../decisions/architecture/DEC-020-defer-archive-package-implementation.md)
  for the current archive package implementation deferral.

## Current Boundary

The accepted prototype flow is:

```text
open read-only handoff package
  -> observe package integrity
  -> pass receiving gate
  -> build ready non-mutating import plan
  -> select one package measurement
  -> build approved durable import request
  -> delegate mutation to Measurement Records durable import
  -> return local handoff import receipt and retry review inputs
```

Handoff adapts package review facts into Measurement Records import inputs. It
does not own durable storage mutation.

The current adapter:

- requires a ready `HandoffImportPlanRun`;
- imports exactly one selected planned measurement per operation;
- requires an approved `HandoffDurableImportRequest`;
- requires caller-declared destination paths for the new durable record;
- maps the package measurement to `MeasurementRecordImportSource` with
  `source_kind="handoff_package"`;
- builds `MeasurementRecordDurableImportRequest` with creation source kind
  `handoff`;
- delegates creation, primary-data writing, read view, finalization, read-model
  projection, no-overwrite handling, and rollback classification to
  `scopecat.measurement_records`;
- returns a local handoff durable-import receipt that records package,
  selected measurement, destination, durable-import classification, and
  explicit non-claims.

Durable-import receipts and summaries include local review guidance for
successful import, blocked import-plan handoff, durable source-preflight
blocks, rollback, and partial-commit cases. That guidance exposes stable
`block_reason`, `next_action`, and `retry_requires` fields without authorizing
retry, reusing stale plans, or bypassing destination/package rechecks.

Public durable-import API functions promote route contract failures to
`HandoffContractError`, which remains `ValueError`-compatible. The
`to_diagnostic()` output is local operator error guidance only; it is not a
portable/export artifact, retry authorization, storage mutation authority, or
public error schema.

The current durable-import schema, policy, local receipt postures, and
non-claims are included in `current_handoff_compatibility_contract()` as a
route-local compatibility review surface. That snapshot preserves the current
production vertical slice expectations without accepting final storage schema,
public SDK, archive, signature/trust, batch durable import, or linked-context
payload import contracts.

DEC-017 keeps multi-measurement package plans as review and coordination
evidence only. They do not authorize one durable batch mutation until a
separate destination, conflict, partial-success, rollback, and retry contract
exists.

The import plan is not write authority. Before mutation, the delegated
Measurement Records pipeline reopens the package member through the package
directory content root and validates digest, byte size, normalized CSV shape,
format, and row count.

## Source Facts

The adapter may consume only reviewed package facts produced by the open
package and ready import-plan path:

| Durable Import Field | Handoff Source |
| --- | --- |
| `source_kind` | `handoff_package` |
| `source_id` | opened package id |
| `source_item_id` | selected package measurement id |
| `content_ref` | selected measurement primary-data package path |
| `declared_digest` | observed package primary-data digest after integrity observation |
| `size_bytes` | observed primary-data byte size, requiring agreement with declared size when present |
| `rows_recorded` | opened primary table row count |
| `primary_data_format` | selected measurement primary format, currently `csv_table` |
| `label`, `experiment_type` | selected package measurement metadata |
| `creation_source_kind` | `handoff` |

Linked context remains review context. Optional managed context-reference
metadata may be preserved in local package, import-plan, and handoff
durable-import review surfaces. DEC-016 keeps packaged linked-context payloads
out of Measurement Records storage until a separate context artifact import
contract exists.

## Artifact And Storage Authority

The handoff package directory and `package-manifest.json` are portable handoff
artifacts. Package contents use package-relative paths and validated managed
references at the package/export boundary.

Durable Measurement Records storage is owned by
`scopecat.measurement_records`. The handoff durable-import adapter owns request
adaptation and local review continuity only.

Local handoff durable-import receipts, receipt summaries, retry reviews, and
CLI summaries are local review surfaces. They are not portable handoff
artifacts, retry approval, persistent GUI state, destination freshness proof,
or storage mutation authority.

DEC-018 allows future GUI receiving surfaces to project these local review
facts, but does not make the durable-import adapter own persisted GUI state.

DEC-019 keeps signature/trust implementation deferred. The durable-import
adapter may consume declared digest integrity from the reviewed package path,
but it does not verify signer identity, trusted source, package authenticity,
or signature-gated mutation policy.

DEC-020 keeps archive creation and extraction deferred. The durable-import
adapter consumes an already-opened directory manifest package; it does not
extract archives, treat archive bytes as durable-import authority, or own
archive materialization cleanup.

## Current Failure Shape

The durable import pipeline reports storage outcomes. Handoff preserves those
outcomes in its local receipt and summary instead of reclassifying storage
semantics.

Expected classifications include:

| Classification | Meaning |
| --- | --- |
| `imported_new_record` | Creation, primary-data write, read view, finalization, and projection completed. |
| `blocked_before_import` | Approval, source facts, destination facts, or preflight validation blocked before storage mutation. |
| `rolled_back_after_import_failure` | Mutation started, then a synchronous failure occurred before final projection and best-effort cleanup ran. |
| `import_failed_after_partial_commit` | A later synchronous failure occurred after a step that the wrapper cannot safely undo. |

Rollback remains best-effort process-local cleanup. It is not crash recovery,
transactional durability, stale-lock cleanup, or concurrent storage-root
protection.

## Out Of Scope

This boundary does not accept:

- importing multiple measurements in one durable operation beyond DEC-017;
- importing into an existing record or attaching to a pre-created shell;
- using the older `measurement_record_directory_candidate_v0` storage layout;
- primary-data merge, compaction, or append visibility as canonical import
  behavior;
- final record-id generation policy;
- manifest replacement or canonical-current-state manifest updates;
- linked-context payload materialization beyond DEC-016;
- archive extraction beyond DEC-020;
- signatures, authenticity, or package trust policy beyond DEC-019;
- adapter discovery, drop-folder protocol, service API, or stable public
  adapter API;
- conflict policy beyond new-record no-overwrite behavior;
- lock identity, stale-lock cleanup, crash recovery, or concurrent writer
  behavior;
- public storage schema, export schema, database index, or GUI import review
  state beyond DEC-018.

## Tests And Fixtures

Active prototype tests live under
[`../../../tests/prototypes/handoff/`](../../../tests/prototypes/handoff/),
especially the durable-import adapter coverage. Handoff fixtures live under
[`../../../tests/fixtures/prototypes/handoff/`](../../../tests/fixtures/prototypes/handoff/)
and selected handoff fixture families under
[`../../../tests/fixtures/`](../../../tests/fixtures/).

Relevant regression expectations:

- successful single-measurement durable import;
- raw-edge composition through import planning and durable import;
- unapproved or not-ready plans block before mutation;
- package-id and selected-measurement mismatches block before mutation;
- stale package bytes are revalidated by the delegated durable-import pipeline;
- linked context remains reference-only review context;
- receipt summaries and retry reviews expose stable local review guidance but
  do not authorize mutation.

Run repository checks with:

```sh
uv run python -m unittest discover -s tests
uv run ruff check .
uv run ruff format --check .
```

## Advancement Questions

Advance this boundary only when a named workflow requires a broader behavior.
Likely separate decisions include:

- batch package receiving/import and partial-success policy beyond DEC-017;
- package archive format beyond DEC-020;
- trust, authenticity, or signature handling beyond DEC-019;
- linked-context payload import beyond DEC-016;
- existing-record update/import conflict behavior;
- persisted receiving review state or GUI durable review workflow beyond DEC-018;
- stronger recovery, locking, or concurrent storage behavior.
