# Existing Record Update Validation Result

## Status

Implementation candidate validated.

This result validates a narrow Measurement Records slice: **Existing Record
Append Update**.

It does not accept final measurement-record update architecture, manifest
replacement, primary-data merge or compaction, read-model refresh, database or
object-store locking, stale-lock repair, crash recovery, schema inference,
import/export package behavior, live service, GUI workflow, hardware control,
or scan execution.

Artifact posture: `internal_validation_summary` for this validation result,
fixture, and expected output. The candidate writes local storage update
artifacts: an append segment and update receipt under the caller-provided
storage root. Those written artifacts are local storage/review artifacts for
this slice, not portable/public or export artifacts.

## Fixture

Fixture:
[`../../tests/fixtures/existing_record_update/basic_append_update/`](../../tests/fixtures/existing_record_update/basic_append_update/)

Implementation candidate:
[`../../implementation_candidates/existing_record_update/`](../../implementation_candidates/existing_record_update/)

The fixture starts with one existing partial measurement record directory under
a caller-provided storage root:

- an existing `record-manifest.json` that declares the current primary-data
  path, sha256 digest, byte size, and row count;
- an existing primary CSV containing the first three rows of a five-point run;
- one approved update request for the same record directory;
- one declared append chunk with sha256, size, event id, sequence, and
  cumulative row-count facts;
- new append-segment and update-receipt paths under the existing record
  directory, plus a direct record-local lock-guard path.

The candidate first checks that the existing record directory is present
without creating it. It then acquires a direct record-local lock guard,
preflights the existing manifest and primary-data file, reads only the declared
update chunk under a caller-provided content root, writes a new append segment
and update receipt, and releases the guard.

## What This Earned

The implementation candidate shows that Scopecat can perform one bounded
mutation against an existing measurement record without turning it into a full
storage update system:

- require an approved existing-record update request before mutation;
- keep storage authority explicit through a caller-provided storage root plus
  declared relative paths;
- require all new update files to stay under the declared existing record
  directory, with the lock-guard path directly under that directory;
- validate existing-record continuity against the current manifest and primary
  data digest/size facts before writing;
- validate append chunk sequence, event id, digest, byte size, previous total,
  new row count, and the expected point-count upper bound;
- refuse preexisting append segment, update receipt, or lock targets without
  overwriting;
- acquire and release a direct record-local lock guard for the fixture mutation;
- write only new append-segment and update-receipt files;
- leave the existing manifest and primary data unchanged;
- return deterministic update results and boundary attention items.

## Boundary

This slice validates one approved append-style update under an existing record
directory.

It does not:

- define final measurement-record storage architecture, update schema,
  database behavior, object-store behavior, retention, or migration strategy;
- validate lifecycle or progress state beyond declared row counts and expected
  point count;
- replace manifests, append to or rewrite primary data, merge segments, compact
  rows, refresh read models, or expose updated primary rows;
- infer source columns, units, row semantics, array shapes, or plot candidates
  from stored or appended data;
- scan storage roots, discover records, repair missing records, or reconcile
  moved paths;
- define distributed locking, lock identity, stale-lock cleanup, concurrent
  writer behavior, or crash recovery beyond refusing an existing lock target
  in this fixture;
- accept import packages, write export packages, or change handoff package
  behavior;
- define live event transport, callbacks, websockets, monitor refresh, or GUI
  behavior;
- control hardware, run scans, mutate parameters, retry failed measurements,
  or make safety decisions.

## Result

Existing-record update closes the first gap after the append-only new-record
writer: Scopecat can now validate a small approved mutation against an already
created measurement record while keeping the mutation append-only at the file
level.

The result is intentionally weaker than a final storage system. The lock is a
fixture-level local guard, not a distributed lock service or lock-identity
contract. The update receipt records the new append evidence, but the existing
manifest and primary data are not replaced or compacted. A later reader or
storage slice must decide how append segments become visible primary data, if
that workflow is needed.

## Follow-Up

Stop this slice at append-segment plus receipt writing unless a later workflow
needs one of these stronger boundaries:

- manifest replacement or read-model refresh after an append update;
- stale-lock review, cleanup, or crash-recovery behavior;
- concurrent writer behavior or live-service coordination;
- compaction of append segments into previewable primary data;
- harder data-shape writer cases such as ragged scans, trace-per-point data,
  or array-valued responses;
- GUI display of in-progress or appended-record state.
