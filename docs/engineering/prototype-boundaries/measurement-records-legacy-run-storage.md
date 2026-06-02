# Legacy Run Storage Inventory Boundary

## Status

Accepted engineering-prototype boundary.

This note owns the first user-facing legacy storage vertical in Measurement
Records: record declared information about an externally executed legacy run,
then list what local storage contains. Live API details belong in
[`../../../src/scopecat/measurement_records/README.md`](../../../src/scopecat/measurement_records/README.md).

## Current Boundary

The accepted post-run legacy storage workflow is:

```text
approved legacy run record request
  -> create Measurement Records shell with creation_source_kind=legacy_system
  -> write record-local legacy-run-receipt.json
  -> optionally attach reviewed converted primary data to the same record
  -> optionally record selected parameter/setup/code/artifact references
  -> later scan records/ for manifests, read models, and legacy receipts
  -> show a compact storage inventory
```

The first operation records declared legacy facts and references only. The
optional attach operation accepts already converted normalized primary data as
reviewed input and writes it into the same legacy record through the existing
writer/read/finalization/projection pipeline. The first user-facing workflow
facade composes those receipt primitives around legacy system id, legacy run
id, converted primary data, and selected references, deriving local Scopecat
ids from the legacy facts instead of asking the caller for receipt request ids
or record ids. The workflow does not open legacy files, parse old formats,
execute old code, observe source payloads, import referenced payloads, repair
references, or decide scientific validity.

## Why This Boundary

The previous Measurement Context direction was starting to promote isolated
candidate summaries without proving a user workflow. This boundary instead
uses already validated concepts as parts of one storage task:

- Measurement Records creation provides durable record shells.
- Legacy sidecar discovery supplies pressure for declared legacy system
  identity, run identity, locators, and context references.
- Existing catalog and operator-review work shows that users need a read-only
  way to see local storage contents.

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
  operation can reuse the existing writer pipeline;
- write one record-local `legacy-run-receipt.json`;
- preserve declared legacy system id, legacy run id, run timing labels,
  declared locators, optional context references, and operator notes;
- attach reviewed converted normalized primary data to the same legacy record
  after validating record-local legacy receipt continuity and source digest,
  byte size, CSV shape, and row count;
- finalize and project that same record through existing receipts/read-models
  without replacing the creation manifest;
- record explicit parameter, setup-binding, code, preliminary-analysis, and
  supporting-evidence references as record-local review receipts;
- compose the above primitives through a prototype user-facing facade that
  accepts legacy facts and converted primary-data facts without requiring the
  user to supply Scopecat ids;
- scan `records/` and list records that have only a manifest, a projected read
  model, a legacy receipt, or a mix of those artifacts;
- surface malformed or missing record-local legacy receipts as review findings.

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
- storage inventory lists both legacy-only records and records with projected
  read models;
- missing or malformed legacy receipts become inventory review findings;
- an approved converted-primary attach writes primary data, writer receipt,
  finalization receipt, and read model into the same legacy record;
- attach requests whose source id does not match the legacy record block before
  mutation;
- attach failures after primary-data mutation roll back only newly attached
  artifacts while preserving the legacy record and legacy receipt;
- a scenario can record multiple legacy measurements through the user-facing
  workflow facade, attach each converted primary data file to its same record,
  record selected references, and render a measurement-oriented review page;
- CLI smoke commands can record a legacy run and list storage inventory.
