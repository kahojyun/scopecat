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
