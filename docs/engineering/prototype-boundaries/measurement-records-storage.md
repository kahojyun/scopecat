# Measurement Records Storage Boundary

## Status

Accepted engineering-prototype boundary.

## Purpose

Own the current durable local Measurement Records boundary: canonical record
lookup, adoption/import/open-by-id, primary-data attach, declared references,
read models, and Measurement Records-owned handoff projection.

Live package-root API orientation lives in
[`../../../src/scopecat/measurement_records/README.md`](../../../src/scopecat/measurement_records/README.md).
Handoff durable import composition is owned by
[`handoff-durable-import-storage.md`](handoff-durable-import-storage.md).

## Boundary

Measurement Records storage is local, caller-rooted durable storage. Canonical
record lookup maps `record_id` to `records/{record_id}`. Package-root facades
hide record-local path construction from callers.

Accepted surface groups:

| Surface | Current Boundary |
| --- | --- |
| JNY-007 adoption facade | Adopt an already-produced measurement through adopt-first or import-ready routes and return a stable local record handle. |
| Canonical import by id | Import reviewed normalized primary data into `records/{record_id}` without caller-supplied record-local paths. |
| Open by id | Open one canonical record by `record_id` and return user-shaped record, source-locator, primary-data, and reference-set summaries. |
| Adopt-first legacy/external route | Create a record shell with declared source identity and locators before reviewed primary data is ready. |
| Primary-data attach | Attach reviewed normalized primary CSV to the same adopted record after continuity and source preflight checks. |
| Recorded references | Write record-local receipts for user-declared context references while leaving referenced payloads outside Measurement Records ownership. |
| Read models | Write replaceable local read summaries for review/export composition, not canonical storage authority. |
| Handoff projection | Project one complete record into packageable JNY-001 facts while owning lookup, read-model freshness, continuity checks, and exportability classification. |

Stored primary-table reads are internal composition helpers for attach, import,
open, and handoff projection paths. They are not a separate package-level API
or workflow boundary.

## Artifact And Storage Authority

Current record-local artifacts include:

- `record-manifest.json` as the immutable creation shell and origin identity;
- record-local receipts for writer, finalization, import, source/adoption
  recording, and references;
- primary CSV bytes written through approved writer/import/attach paths;
- derived `record-read-model.json` as a replaceable local convenience summary.

Current authority model:

- adoption/import operations own initial manifest creation;
- import/attach operations own primary CSV bytes and their receipts;
- read-model refresh owns derived summaries, not canonical manifest
  replacement;
- handoff preparation owns packageable projection, not package writing.

## Adopt-First Route

Adopt-first recording preserves declared facts about an externally produced,
legacy-backed, notebook-backed, or manually reviewed run without parsing source
payloads or replacing the producing system.

The route may:

- create one new canonical record under a caller-provided storage root;
- set creation source facts such as `legacy_system` or another explicit source
  kind;
- preserve declared source/run ids, locators, and operator notes;
- optionally attach reviewed normalized primary data later to the same record;
- optionally record parameter, setup, code, artifact, analysis, or supporting
  evidence references as record-local reference receipts.

Import-ready recording is the same JNY-007 recording workflow when reviewed
normalized primary data is already available at creation time.

## Non-Claims

This boundary does not accept:

- legacy file observation, legacy parsing, notebook execution, runner hooks,
  hardware control, adapter discovery, or source workspace scanning;
- automatic reference repair, referenced payload import, relation traversal, or
  final cross-route context schema;
- creating a second imported record for the same user measurement;
- manifest replacement, repair, broad conflict resolution, stale-lock cleanup,
  crash recovery, or concurrent storage mutation;
- public storage schema, public export schema, shared id-generation policy,
  database index, GUI state, JNY-008 browse/plot UX, or scientific validity
  claims.

## Advancement Questions

Advance this boundary only when a named workflow requires broader storage
behavior, such as existing-record merge import, manifest replacement,
referenced payload import, running-monitor durable decisions, GUI state
persistence, stronger recovery/locking, or final storage schema publication.
