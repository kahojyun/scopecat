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

The first projected file must be named `record-read-model.json`. It may
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

## Read Model Projection Implementation Checkpoint

The first derived read-model projection slice is implemented in
[`../../../scopecat/measurement_records/`](../../../scopecat/measurement_records/).
It exposes a raw-dictionary entrypoint,
`project_measurement_record_read_model(...)`, and a typed request entrypoint,
`project_measurement_record_read_model_from_read_view(...)`.

This slice consumes a read view, re-reads and verifies the creation manifest
and writer receipt against that read view, reads a record-local
`finalization-receipt.json`, verifies finalization evidence continuity, and
writes exactly one record-local `record-read-model.json` under no-overwrite
behavior. The read model summarizes final lifecycle state, source receipt
paths and digests, primary data facts, table preview data, and review findings.

It deliberately keeps `record-read-model.json` as a derived local convenience
surface. It does not replace `record-manifest.json`, mutate receipts, overwrite
or refresh an existing read model, define canonical storage authority, accept
public export schema, implement stale projection repair, or define crash
recovery.

## Read Model Catalog Implementation Checkpoint

The first read-only catalog slice is implemented in
[`../../../scopecat/measurement_records/`](../../../scopecat/measurement_records/).
It exposes a raw-dictionary entrypoint,
`catalog_measurement_record_read_models(...)`, and a typed request entrypoint,
`catalog_measurement_record_read_models_from_request(...)`.

This slice scans a caller-declared records directory for record-local
`record-read-model.json` files, validates the projected read-model shape,
returns compact catalog entries, and reports missing, malformed, conflicting,
or source-digest-stale projections as review findings. Source consistency is
limited to the creation manifest, writer receipt, and finalization receipt
digests already declared by the projected read model.

It deliberately performs no storage mutation. It does not refresh or repair
read models, replace manifests, revalidate primary data, define conflict
resolution, create a database index, promote public export schema, or define
canonical storage authority.

## Read Model Refresh Decision

Choose explicit, approved read-model refresh with atomic replacement of the
derived `record-read-model.json` only.

The next slice should prove:

```text
creation manifest
  -> writer receipt
  -> read-view summary
  -> finalization receipt
  -> approved refresh request
  -> temporary record-local read model
  -> atomic replacement of record-read-model.json
  -> local refresh run receipt
```

Refresh recomputes the read model from authoritative prototype inputs: the
creation manifest, writer receipt, read view, and finalization receipt. It
must not trust the previous read model as source evidence. The previous
`record-read-model.json` is only an overwrite guard and stale-state target.
Receipts and the creation manifest continue to win over the projected read
model after refresh.

The first refresh implementation should:

- require an approved refresh request;
- consume the same authoritative inputs as the projection slice;
- require record id, record directory, manifest path, writer receipt path,
  primary data path, digest, size, row-count, and finalization continuity;
- require the caller to declare the expected target condition as `missing` or
  `replace_existing`;
- for `replace_existing`, require an expected current
  `record-read-model.json` digest before replacement;
- write a temporary read model under the same record directory;
- atomically replace `record-read-model.json` only after the temporary model is
  complete;
- best-effort remove the temporary file on synchronous failure;
- leave the creation manifest, writer receipt, primary data, and finalization
  receipt unchanged.

Refresh is allowed when the catalog reports a missing, malformed, conflicting,
or source-digest-stale read model, but the refresh operation itself should
validate against the authoritative inputs rather than against the catalog
finding. If the authoritative inputs no longer agree, refresh should block
before replacement.

This decision does not accept:

- replacing, rewriting, or atomically swapping `record-manifest.json`;
- treating `record-read-model.json` as canonical storage authority;
- repairing or mutating writer receipts, finalization receipts, primary data,
  or creation manifests;
- accepting broad overwrite without an expected current target condition;
- lock identity, stale-lock cleanup, concurrent refresh, or distributed
  transaction semantics;
- public storage schema, export schema, database index refresh, or GUI review
  state.

If refresh fails before atomic replacement, the previous read model should
remain in place when it existed. If refresh fails after a successful atomic
replacement, the operation should report that replacement occurred and should
not attempt rollback in the first slice. Stronger crash recovery and lock
identity remain separate storage-hardening decisions.

## Read Model Refresh Implementation Checkpoint

The first read-model refresh slice is implemented in
[`../../../scopecat/measurement_records/`](../../../scopecat/measurement_records/).
It exposes a raw-dictionary entrypoint,
`refresh_measurement_record_read_model(...)`, and a typed request entrypoint,
`refresh_measurement_record_read_model_from_read_view(...)`.

This slice recomputes `record-read-model.json` from a read view plus the
authoritative creation manifest, writer receipt, and finalization receipt. It
requires an approved refresh request and a caller-declared target condition:
`missing` or `replace_existing`. `replace_existing` requires an expected
current read-model digest. Refresh writes a temporary record-local model and
uses atomic replacement for the final `record-read-model.json`.

It deliberately treats the previous read model only as an overwrite guard. It
does not replace `record-manifest.json`, mutate receipts, repair primary data,
accept broad overwrite, define concurrent refresh, implement lock identity, or
promote canonical storage authority.

## Manifest Replacement Decision

Do not replace `record-manifest.json` in the current measurement-record
prototype line.

The accepted authority model remains:

```text
record-manifest.json
  -> immutable creation shell and origin identity
writer-receipt.json
  -> authoritative primary-data materialization evidence
finalization-receipt.json
  -> authoritative lifecycle finalization evidence
record-read-model.json
  -> derived convenience projection, refreshable by approved atomic replace
```

`record-manifest.json` should continue to describe the created record shell:
record id, record directory, initial lifecycle state, creation provenance, and
explicit non-claims. Current lifecycle state, primary-data facts, and compact
consumer summaries should come from receipts and derived read models, not from
manifest mutation.

This decision is intentionally conservative. Manifest replacement would create
a second canonical-current-state surface beside receipts and read models. That
would require authority rules for conflicts, atomic manifest swap semantics,
lock identity, stale read-model invalidation, crash recovery, and import/update
merge policy. The current prototype evidence does not need those costs yet:
writer integration, finalization, projection, catalog, and refresh are already
covered by receipt authority plus derived projections.

The next implementation slice should not implement manifest replacement.
Future work should revisit manifest replacement only after a separate route
proves a concrete need that receipts plus refreshed read models cannot satisfy,
such as:

- existing-record update that must publish a single canonical current manifest;
- import or handoff merge that requires canonical primary-data membership
  inside `record-manifest.json`;
- archival/export packaging that refuses derived projections as the summary
  surface;
- multi-writer coordination that requires lock identity and canonical current
  state in one atomically replaced file.

Any future manifest replacement decision must define at least:

- manifest schema versioning and compatibility with creation manifests;
- expected-current manifest digest or equivalent conflict guard;
- temporary-file naming and atomic replacement semantics;
- whether refreshed read models become stale before or after manifest replace;
- crash recovery, partial-write cleanup, and stale-lock handling;
- receipt-versus-manifest conflict authority;
- import/update merge semantics;
- public/export boundary posture if replacement manifests leave the local
  workspace.

Until that later decision exists, a stale or missing read model should be
handled by read-model refresh, not by replacing the creation manifest. A stale
or conflicting receipt should remain a review finding or route-specific error,
not a manifest repair trigger.

## In-Progress Update Decision

Choose append-receipt visibility for the first in-progress record update.

The next slice should prove:

```text
in_progress creation manifest
  -> writer receipt and existing primary data
  -> approved append update request
  -> record-local append segment
  -> record-local update receipt
  -> read-only running inspection view
```

This slice keeps the current receipt authority model. The existing primary
data file remains the first materialized segment, append segments remain
separate update evidence, and the creation manifest and read model are not
rewritten. A read-only inspection view may make declared append receipts
visible for local monitoring, but it does not make append segments canonical
primary data.

The first implementation should:

- require an existing creation manifest whose lifecycle state is `in_progress`;
- require an existing record-local writer receipt and matching primary data
  digest, size, row count, and record identity;
- require an approved append update request;
- validate one declared append chunk by digest, byte size, previous row total,
  and total row progress;
- require second and later append requests to declare the previous update
  receipt so append progress is contiguous from the writer receipt through the
  update receipt chain;
- write exactly one append segment and one update receipt with no-overwrite
  behavior;
- return a local update receipt summary;
- provide a read-only inspection view over the writer receipt plus
  caller-declared update receipts;
- provide a compact local running-inspection summary with latest visible rows,
  progress, review finding codes, and a suggested next local action.
- expose a narrow read-only CLI smoke entrypoint for printing that compact
  summary from caller-declared storage root and receipt paths.

This decision does not accept:

- manifest replacement or canonical lifecycle-state update;
- merging, compacting, or appending into the primary data file;
- read-model refresh from append receipts;
- finalization semantics for in-progress records;
- lock identity, stale-lock cleanup, concurrent update behavior, or crash
  recovery;
- GUI-owned running monitor state or saved fit/review decisions.

## In-Progress Update Implementation Checkpoint

The first in-progress update and inspection slice is implemented in
[`../../../scopecat/measurement_records/`](../../../scopecat/measurement_records/).
It exposes raw-dictionary and typed entrypoints:
`append_in_progress_measurement_record(...)`,
`append_in_progress_measurement_record_from_request(...)`,
`inspect_running_measurement_record(...)`, and
`inspect_running_measurement_record_from_request(...)`.

This slice consumes an `in_progress` creation manifest, a writer receipt, and a
declared append chunk. It writes one append segment and one update receipt
under no-overwrite behavior, then lets the inspection view read the base
primary table plus caller-declared update receipts as visible in-progress
rows. Tests prove successful append/inspection, unapproved no-mutation,
non-`in_progress` lifecycle blocking, digest mismatch blocking before
mutation, update-receipt rollback, progress mismatch review findings, and
non-contiguous update receipt rejection. Follow-up coverage proves compact
inspection summaries, second append requests through a declared previous
update receipt, ordinary multiple-receipt inspection, and rejection of a gap
between multiple append receipts. The module also exposes
`python -m scopecat.measurement_records running-inspection-summary` as a
read-only smoke CLI for printing the compact local summary from
caller-declared paths.

It deliberately does not replace manifests, merge primary data, refresh read
models, finalize lifecycle state, define lock/crash recovery behavior, or
persist GUI monitor state. The CLI does not discover records, scan update
directories, mutate storage, or persist monitor state.

## Running Monitor Affordance Posture

Temporary monitor affordances such as row-range selection or parabolic fit
preview remain ephemeral in this prototype line. They may be useful local UI or
notebook behavior, but they should not become durable record mutation unless a
later slice defines a saved review receipt that records the selected range,
fit input rows, fit result, operator decision, and non-claims.

This keeps running inspection focused on readable progress and review findings.
It does not accept automatic retune, scan-plan adjustment, parameter write-back,
saved GUI state, or scientific fit validity as part of the current
Measurement Records storage boundary.

## Operator Review Composition Checkpoint

The first read-only operator-review composition slice is implemented in
[`../../../scopecat/measurement_records/`](../../../scopecat/measurement_records/).
It exposes raw-dictionary and typed entrypoints:
`review_measurement_records(...)` and
`review_measurement_records_from_request(...)`.

This slice composes the existing read-model catalog with optional
caller-declared running inspections:

```text
records directory
  -> catalog projected read models
  -> optional caller-declared running inspection requests
  -> selected local record summary
  -> aggregated operator-review findings
```

It deliberately remains read-only. It does not refresh read models, discover
update receipts, replace manifests, finalize lifecycle state, repair storage,
mutate records, define canonical storage authority, or persist GUI review
state. Missing projected read models still surface through the catalog, but an
in-progress record that is explicitly supplied through a running inspection is
not treated as a top-level operator-review problem merely because it lacks a
derived read model.

The module also exposes
`python -m scopecat.measurement_records operator-review` as a narrow local CLI
smoke surface for printing the composed review JSON from a caller-declared
storage root and optional running-inspection paths. The CLI does not discover
records beyond the catalog directory, scan update directories, mutate storage,
or perform refresh, import, finalization, repair, or GUI-state persistence.
