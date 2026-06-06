# Legacy Run Storage Boundary

## Status

Accepted engineering-prototype boundary.

This note owns the first user-facing legacy storage vertical in Measurement
Records: record declared information about an externally executed legacy run,
then optionally attach converted primary data to the same record. Live API
details belong in
[`../../../src/scopecat/measurement_records/README.md`](../../../src/scopecat/measurement_records/README.md).

## Current Boundary

The accepted post-run legacy storage workflow is:

```text
approved legacy run record request
  -> create Measurement Records shell with creation_source_kind=legacy_system
  -> write record-local legacy-run-receipt.json
  -> optionally attach reviewed converted primary data to the same record
  -> optionally record selected parameter/setup/code/artifact references
```

The first operation records declared legacy facts and references only. The
optional attach operation accepts already converted normalized primary data as
reviewed input and writes primary data, writer receipt, finalization receipt,
and read model into the same legacy record. Earlier workflow-facade code that
composed these primitives for a scenario has been retired from the active
package surface. The active boundary remains the lower-level storage
operations until a named JNY-007 route earns a user-facing orchestration shape.
JNY-007 should be read as one recording workflow with route variants:
adopt-first recording for source identity before reviewed primary data is
ready, and import-ready recording when reviewed normalized primary data can
create the record directly. The direct durable import route is a separate
validation segment because its API and failure behavior differ, not because it
is a separate product journey.
These operations do not open legacy files, parse old formats, execute old code,
observe source payloads, import referenced payloads, repair references, or
decide scientific validity.

## Why This Boundary

The previous Measurement Context direction was starting to promote isolated
candidate summaries without proving a user workflow. This boundary instead
uses already validated concepts as parts of one storage task:

- Measurement Records creation provides durable record shells.
- Legacy sidecar discovery supplies pressure for declared legacy system
  identity, run identity, and locators.
- Selected-record handoff shows that stored records need a compact read model
  that downstream package export can consume.

The prototype is intentionally storage-first. A legacy-only record can be
visible before primary data is attached, and that visibility is useful by
itself. When converted primary data later becomes available, the user-facing
measurement should remain the same record rather than split into a legacy
record and an imported-record mirror.

## Accepted Behavior

The live prototype may:

- create one new record directory under a caller-provided storage root;
- write the usual `record-manifest.json` with `creation_source_kind` set to
  `legacy_system`;
- set the initial lifecycle state to `created` so an explicit approved attach
  operation can add converted primary data later;
- write one record-local `legacy-run-receipt.json`;
- preserve declared legacy system id, legacy run id, run timing labels,
  declared locators, and operator notes;
- attach reviewed converted normalized primary data to the same legacy record
  after validating record-local legacy receipt continuity and source digest,
  byte size, CSV shape, and row count;
- finalize and project that same record through existing receipts/read-models
  without replacing the creation manifest;
- record explicit parameter, setup-binding, code, preliminary-analysis, and
  supporting-evidence references as record-local reference receipts.

## Out Of Scope

This boundary does not accept:

- legacy code execution, runner hooks, notebook execution, or hardware control;
- legacy file observation, checksum validation, payload import, preview
  generation, adapter transport, or schema inference;
- legacy primary-data parsing, automatic adapter discovery, or legacy payload
  import;
- creating a second imported record for the same user measurement;
- manifest replacement, repair, conflict resolution beyond no-overwrite, crash
  recovery, or concurrent storage mutation;
- canonical GUI state, public export schema, shared context schema, or
  scientific validity claims.
- final public SDK shape or shared id-generation policy.

## Stop Condition

Stop this slice when tests prove:

- an approved legacy record request writes a record shell plus receipt;
- unapproved requests do not mutate storage;
- declared legacy locators are stored without observing whether target files
  exist;
- an approved converted-primary attach writes primary data, writer receipt,
  finalization receipt, and read model into the same legacy record;
- attach requests whose source id does not match the legacy record block before
  mutation;
- attach failures after primary-data mutation roll back only newly attached
  artifacts while preserving the legacy record and legacy receipt.
