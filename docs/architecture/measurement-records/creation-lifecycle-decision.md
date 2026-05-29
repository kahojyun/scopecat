# Measurement Record Creation Lifecycle Decision

## Status

Engineering prototype decision, not an ADR.

This note owns the first Measurement Records engineering prototype for durable
record creation. It uses existing discovery and handoff evidence rather than
opening a new broad discovery pass. It defines the smallest creation lifecycle
boundary needed before later storage/import decisions can choose conflict
policy, existing-record import, or stronger recovery behavior. Keep live API
syntax in
[`../../../scopecat/measurement_records/README.md`](../../../scopecat/measurement_records/README.md).

Artifact posture: `internal_validation_summary`. This note is internal project
memory. It creates no portable package output, public contract, public SDK, or
new redaction rule. Use
[`discovery/policies/artifact-boundary-and-redaction.md`](../../discovery/policies/artifact-boundary-and-redaction.md)
if any future output is promoted into a portable/export artifact.

## Decision

Start a narrow production-prototype slice for measurement-record creation.

The prototype should prove one approved creation operation:

```text
approved creation request
  -> caller-provided storage root
  -> caller-provided or policy-selected record id
  -> no-overwrite record directory creation
  -> initial record manifest
  -> local creation receipt
```

The prototype is not final storage architecture. It should establish the first
durable record shell that later writer, import, update, handoff, and source
observation work can reference without turning any candidate storage layout
into the final schema.

## Why This Can Start Now

Current evidence is sufficient for this narrow engineering decision:

- New-run writer semantics already validates explicit writer events and
  lifecycle/progress summaries before storage mutation.
- Append-only storage writer already validates approved new-record storage
  mutation under caller-provided roots and no-overwrite paths.
- Existing-record append update already validates that updates need a real
  existing record boundary before append evidence is written.
- Running measurement inspection already validates that in-progress or partial
  recorded data can be ordinary state rather than a warning by itself.
- Legacy import acceptance and handoff storage acceptance both need a durable
  new-record target before final import behavior can be chosen.
- Handoff storage/import requirements synthesis identifies record creation as
  the next gate before broader import/storage mutation.

The missing piece is not more discovery vocabulary. It is a small creation
operation that names record identity, initial state, and failure behavior
without deciding update, merge, import, archive, or GUI policy.

## First Prototype Contract

The first implementation should:

- require an explicit approved creation request;
- accept a caller-provided storage root and validate it as the mutation root;
- accept a declared record id for the first slice, or a route-local allocator
  only if the allocator's uniqueness and collision behavior are part of the
  same tests;
- create exactly one new record directory with no-overwrite behavior;
- write exactly one initial `record-manifest.json`;
- return a local creation receipt with created paths, record id, initial
  lifecycle state, and non-claim metadata;
- reject preexisting record directories or manifest paths without overwrite,
  rename, merge, or dedupe;
- roll back files and empty directories created by the current operation when
  synchronous manifest writing fails;
- keep raw dictionary validation at the public edge and use typed route-local
  objects internally if this becomes accepted implementation code.

The first manifest should be intentionally small. It may include:

- schema name such as `measurement_record_creation_candidate_v0`;
- record id;
- creation source kind such as `manual`, `writer`, `import`, or `handoff`,
  only as declared provenance, not as workflow authority;
- initial lifecycle state;
- created timestamp if supplied by the caller or injected clock;
- optional label or experiment metadata as reviewed free text;
- empty or absent primary-data references;
- explicit non-claims for final storage schema, import policy,
  existing-record update, read-model refresh, conflict resolution, and
  scientific validity.

## Initial Lifecycle Scope

The first prototype should keep lifecycle vocabulary small:

| State | Meaning |
| --- | --- |
| `created` | Durable record shell exists, but no primary data has been written or accepted. |
| `in_progress` | Durable record shell exists and future writer/update evidence may add primary data. |
| `review_needed` | Durable record shell exists, but the next operation needs operator review before more mutation. |

The first slice should not use `complete` or `failed` as durable terminal
states unless it also owns the data-writing or finalization operation that
proves them. Writer-event summaries may still report completion or failure as
their own review facts; this creation slice should not turn those into final
record lifecycle semantics.

## Out Of Scope

This decision does not accept:

- final measurement-record storage schema, index, database, object store, or
  public storage API;
- package import acceptance, adapter import acceptance, or import into an
  existing record;
- final record-id generation policy beyond the first prototype boundary;
- manifest replacement, primary-data merge, compaction, or read-model refresh;
- append-segment visibility as primary data;
- conflict policy beyond no-overwrite blocking;
- lock identity, stale-lock cleanup, concurrent writer behavior, crash
  recovery, or transactional durability;
- archive extraction, signatures, authenticity, or trust policy;
- linked-context payload import or recursive relation traversal;
- GUI-owned creation flow, durable cross-session review state, or user
  interaction model;
- shared measurement-record domain model across routes.

## Prototype Stop Condition

Stop the first creation prototype when tests prove:

- approved creation succeeds for one new record directory;
- blocked or unapproved creation does not mutate storage;
- preexisting destination paths block creation;
- malformed record ids or destination paths are rejected before mutation;
- manifest write failure rolls back current-operation files and created empty
  directories;
- the receipt and manifest preserve the declared record id, storage root
  continuity, initial state, and explicit non-claims.

After that, choose a separate next decision:

- writer integration: attach writer/storage-writer output to a created record;
- import integration: decide whether handoff or adapter import creates a new
  record, attaches to a created shell, or updates an existing record;
- lifecycle finalization: define `complete`, `failed`, or other terminal
  states after data writing;
- storage hardening: define lock identity, stale cleanup, crash recovery, and
  conflict policy.

Do not expand the creation prototype into final storage/import behavior in the
same slice.

## Implementation Checkpoint

The first prototype is implemented in
[`../../../scopecat/measurement_records/`](../../../scopecat/measurement_records/).
It exposes a raw-dictionary entrypoint,
`create_measurement_record(...)`, and a typed request entrypoint,
`create_measurement_record_from_request(...)`.

The implemented slice proves approved creation, unapproved no-mutation,
preexisting destination blocking, malformed id/path rejection before mutation,
symlink-parent rejection, initial manifest writing, local receipt projection,
and best-effort rollback when manifest writing fails. It keeps `record_id`
caller-declared and public-safe; it does not generate UUIDs, allocate
namespace ids, or parse record ids for meaning.

## Writer Integration Checkpoint

The first writer-integration slice is also implemented in
[`../../../scopecat/measurement_records/`](../../../scopecat/measurement_records/).
It exposes a raw-dictionary entrypoint,
`write_created_record_primary_data(...)`, and a typed request entrypoint,
`write_created_record_primary_data_from_request(...)`.

This slice consumes an existing creation manifest, verifies record id, record
directory, manifest path, lifecycle state, and `primary_data: not_recorded`
continuity, preflights declared chunk digest and size facts, then writes
primary data plus a record-local writer receipt under no-overwrite behavior.
It proves unapproved no-mutation, target collision blocking, malformed path
rejection, digest mismatch rejection before mutation, and rollback when the
writer receipt fails after primary data is written.

It deliberately does not replace the creation manifest, refresh a read model,
mark a record `complete` or `failed`, merge existing primary data, import
packages, define conflict resolution beyond no-overwrite, or promote final
storage schema.

## Read View Checkpoint

The first read-view slice is implemented in
[`../../../scopecat/measurement_records/`](../../../scopecat/measurement_records/).
It exposes a raw-dictionary entrypoint,
`read_created_record_primary_table(...)`, and a typed request entrypoint,
`read_created_record_primary_table_from_request(...)`.

This slice consumes an existing creation manifest and a caller-provided
record-local writer receipt path. It verifies record id, record directory,
creation manifest path, writer receipt path, primary data path, digest, and
size continuity before reading the writer-receipt-declared primary CSV as
string-valued table rows. It reports row-count mismatch as a review finding
and rejects malformed CSV, missing writer receipts, symlink targets, and
continuity mismatches.

It deliberately does not replace the creation manifest, refresh a read model,
finalize lifecycle state, infer schema or scalar types, build plot series,
invoke dataframe adapters, or promote final storage schema.

## Lifecycle Finalization Decision

Choose receipt-based lifecycle finalization as the next implementation
boundary.

The next slice should prove:

```text
creation manifest
  -> writer receipt
  -> read-view summary
  -> approved finalization request
  -> record-local finalization receipt
  -> local finalization run receipt
```

This decision deliberately does not replace `record-manifest.json`. The
creation manifest remains the durable shell record for this prototype phase.
The finalization receipt records reviewed finalization evidence beside it so a
later manifest-replacement or read-model-refresh decision has explicit input
to consume.

The first finalization states are:

| State | Meaning |
| --- | --- |
| `complete` | Approved finalization says the writer receipt and read view agree that primary data exists, is digest/size checked, is readable as normalized CSV rows, and matches the expected row count. |
| `failed` | Approved finalization records that the record should stop as failed, with an explicit operator reason and reviewed evidence. |

`complete` should require a ready read view with no review findings. `failed`
should require an operator reason and should not be inferred automatically
from writer errors, missing files, row-count mismatch, or read failures. Those
conditions may justify a failed finalization request, but the finalization
state itself is still an approved review decision.

The first implementation should:

- require an approved finalization request;
- consume the existing creation manifest, writer receipt, and read-view run;
- require record id, record directory, creation manifest path, writer receipt
  path, primary data path, digest, size, and row-count continuity;
- write exactly one `finalization-receipt.json` under the record directory
  with no-overwrite behavior;
- return a local finalization run receipt;
- reject a `complete` request when the read view has review findings;
- require a single-line operator reason for `failed`;
- leave the creation manifest unchanged.

This decision does not accept:

- manifest replacement or canonical lifecycle-state update;
- read-model refresh;
- final storage schema;
- conflict policy beyond no-overwrite receipt creation;
- crash recovery, stale-lock cleanup, or concurrent storage-root mutation;
- import finalization semantics;
- GUI-owned finalization review state.

After this slice, choose a separate decision for manifest replacement/read
model refresh if consumers need final lifecycle state without consulting the
finalization receipt.

## Finalization Implementation Checkpoint

The first receipt-based finalization slice is implemented in
[`../../../scopecat/measurement_records/`](../../../scopecat/measurement_records/).
It exposes a raw-dictionary entrypoint, `finalize_measurement_record(...)`,
and a typed request entrypoint,
`finalize_measurement_record_from_read_view(...)`.

This slice consumes a ready read view, validates continuity with the creation
manifest and writer receipt, and writes exactly one record-local
`finalization-receipt.json` under no-overwrite behavior. `complete`
finalization requires a ready read view with no findings. `failed`
finalization requires an explicit single-line operator reason and remains an
approved review decision, not an automatic consequence of writer or read
errors.

It deliberately leaves `record-manifest.json` unchanged and does not refresh a
read model, define canonical lifecycle-state storage, implement crash
recovery, or accept import finalization semantics.

## Read Model Projection Decision

Choose derived read-model projection before manifest replacement.

The next slice should prove:

```text
creation manifest
  -> writer receipt
  -> read-view summary
  -> finalization receipt
  -> approved projection request
  -> record-local read model
  -> local projection run receipt
```

The projected read model is a convenience surface for local consumers that need
one current-state summary. It is not canonical storage authority. Until a
separate manifest-replacement decision exists, `record-manifest.json` remains
the durable shell, writer and finalization receipts remain authoritative
evidence, and receipt contents win over a stale or conflicting read model.

The first projected file should be named `record-read-model.json`. It may
summarize:

- record id and record directory;
- creation manifest path and digest;
- writer receipt path, primary data path, primary data digest, byte count, and
  declared row count;
- read-view status, observed row count, and review findings;
- final lifecycle state from `finalization-receipt.json`;
- failed finalization reason when the final state is `failed`;
- source receipt paths and projection non-claims.

The first implementation should:

- require an approved projection request;
- consume the existing creation manifest, writer receipt, read-view run, and
  finalization receipt;
- require record id, record directory, manifest path, writer receipt path,
  primary data path, digest, size, row-count, and finalization continuity;
- write exactly one `record-read-model.json` under the record directory with
  no-overwrite behavior;
- return a local projection run receipt;
- leave the creation manifest, writer receipt, primary data, and finalization
  receipt unchanged.

This decision does not accept:

- replacing, rewriting, or atomically swapping `record-manifest.json`;
- treating `record-read-model.json` as canonical authority;
- refreshing or overwriting an existing read model;
- stale read-model detection, repair, or cleanup;
- conflict policy beyond no-overwrite projection creation;
- crash recovery, lock identity, concurrent refresh, or transactional
  durability;
- public storage schema, export schema, database index, or GUI review state.

Manifest replacement remains a later decision because it needs atomic replace
semantics, stale projection handling, conflict policy, crash recovery, and
clear authority rules. This projection slice only unblocks consumers that need
a compact current-state summary after receipt-based finalization.
