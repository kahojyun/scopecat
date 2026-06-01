# Legacy Run Storage Inventory Decision

## Status

Engineering prototype decision, not an ADR.

This note owns the first user-facing legacy storage vertical in Measurement
Records: record declared information about an externally executed legacy run,
then list what local storage contains. Live API details belong in
[`../../../scopecat/measurement_records/README.md`](../../../scopecat/measurement_records/README.md).

Artifact posture: `internal_validation_summary`. This note is internal project
memory. It creates no portable package output, public contract, public SDK, or
new redaction rule.

## Decision

Accept a narrow post-run legacy storage workflow:

```text
approved legacy run record request
  -> create Measurement Records shell with creation_source_kind=legacy_system
  -> write record-local legacy-run-receipt.json
  -> later scan records/ for manifests, read models, and legacy receipts
  -> show a compact storage inventory
```

The workflow records declared legacy facts and references only. It does not
import primary data, open legacy files, parse old formats, execute old code,
observe source payloads, repair references, refresh read models, or decide
scientific validity.

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
visible before primary data is imported, and that visibility is useful by
itself.

## Accepted Behavior

The live prototype may:

- create one new record directory under a caller-provided storage root;
- write the usual `record-manifest.json` with `creation_source_kind` set to
  `legacy_system`;
- set the initial lifecycle state to `review_needed`;
- write one record-local `legacy-run-receipt.json`;
- preserve declared legacy system id, legacy run id, run timing labels,
  declared locators, optional context references, and operator notes;
- scan `records/` and list records that have only a manifest, a projected read
  model, a legacy receipt, or a mix of those artifacts;
- surface malformed or missing record-local legacy receipts as review findings.

## Out Of Scope

This decision does not accept:

- legacy code execution, runner hooks, notebook execution, or hardware control;
- legacy file observation, checksum validation, payload import, preview
  generation, adapter transport, or schema inference;
- primary data import into the legacy record;
- manifest replacement, read-model refresh, finalization, repair, conflict
  resolution, crash recovery, or concurrent storage mutation;
- canonical GUI state, public export schema, shared context schema, or
  scientific validity claims.

## Stop Condition

Stop this slice when tests prove:

- an approved legacy record request writes a record shell plus receipt;
- unapproved requests do not mutate storage;
- declared legacy locators are stored without observing whether target files
  exist;
- storage inventory lists both legacy-only records and records with projected
  read models;
- missing or malformed legacy receipts become inventory review findings;
- CLI smoke commands can record a legacy run and list storage inventory.
