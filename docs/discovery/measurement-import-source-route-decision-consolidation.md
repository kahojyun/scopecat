# Measurement Import And Source Route Decision Consolidation

## Status

Discovery decision consolidation, not an ADR.

This note closes the current measurement import/source-reference discovery
pass. It records the route decisions earned by the validated adapter-authored
legacy import, legacy import acceptance, reference-only import, reference-only
source observation, append-only storage writer, and measurement source
observation slices.

It does not accept a stable import API, adapter API, legacy reader, final
storage schema, existing-record update behavior, reference repair, package
format, GUI contract, dataframe API, schema-inference engine, or shared
measurement-record domain model.

Artifact posture: `internal_validation_summary`. This document is internal
project memory. It creates no portable/export artifact and no new redaction
rules. Use
[`artifact-boundary-and-redaction-policy.md`](artifact-boundary-and-redaction-policy.md)
for artifact-boundary classification.

## Accepted For Now

The current route separates **legacy source**, **normalized primary data**,
and **observed file facts**:

```text
legacy system data
  -> user/lab adapter output
  -> reviewed adapter-authored manifest
  -> choose copy acceptance or reference-only acceptance
  -> optionally observe file facts
  -> optionally read normalized primary data through a later validated route
```

Scopecat should not parse arbitrary legacy systems in core. Legacy-specific
knowledge belongs in user-owned or lab-owned adapters unless a later slice
explicitly accepts a core reader.

Adapter output can carry two distinct things:

- an external source reference to original or lab-managed legacy data, for
  provenance and later file-level observation;
- normalized primary data in a Scopecat-understood shape, for preview, copy,
  package, SDK/table access, and plotting only through routes that validate
  those actions.

Reference-only import is a provenance and review posture. It preserves a
current external source reference and linked context without copying primary
data, mutating storage, opening the source, or enabling plots.

File-level source observation checks only file facts such as availability,
sha256, and byte size for one explicit external source reference. It does not
earn data parsing, row counts, schema validation, preview verification, plot
readiness, repair, or import acceptance.

Copy acceptance owns one approved copy-into-new-record mutation for reviewed
adapter-normalized primary data. The copied file is Scopecat-readable only
because the adapter output is normalized, not because the legacy source exists
or was observed.

Stored source observation is a separate read-only check over a declared
normalized primary-data file under a caller-provided storage root. Its current
row-count check is data-level evidence for the validated normalized fixture,
not a generic schema inference engine.

Declared preview metadata from adapters is useful as an assertion. It becomes
Scopecat-observed previewability only when normalized data access or an
explicit adapter authority has been validated by the relevant slice.

## Route Concepts

| Concept | Current meaning | Not implied |
| --- | --- | --- |
| External source reference | A pointer to original or lab-managed data outside Scopecat storage, with source identity, reference state, redacted display facts, and optional file-level observations. | Parseable primary data, plot readiness, repair, backup, or ownership of the external system. |
| Adapter-normalized primary data | Data produced or declared by an adapter in a Scopecat-understood shape and reviewed as the primary data item for copy, storage, package, or read routes. | Stable adapter API, core legacy reader, inferred schema, or final storage model. |
| Reviewed adapter facts | The subset of manifest or acceptance facts another slice can consume without replaying the whole prior candidate. | A shared summary schema or reusable measurement domain model. |
| File-level observation | Availability, digest, size, mtime-like facts for a concrete path under a caller-provided root. | Row count, column/schema validation, preview verification, scientific validity, or reference repair. |
| Data-level observation | A read using a declared supported data model, such as the current normalized CSV/table fixtures. | Automatic support for every CSV, HDF5, LabRAD, DataVault, Labber, ndarray, or future table shape. |
| Linked context reference | A related parameter snapshot, artifact, note, or external object carried by relation facts. | Recursive traversal, payload import, or display semantics beyond the validated linked-context slice. |

## Current Track Map

| Track | Current slices | Earned responsibility |
| --- | --- | --- |
| Incoming orientation | Incoming measurement record import preview | Classify explicit incoming manifests without file reads or import acceptance. |
| Adapter normalization | Adapter-authored legacy import manifest | Validate reviewed adapter-authored manifest facts with adapter-normalized primary data and external source identity. |
| Copy acceptance | Legacy import acceptance | Copy one reviewed adapter-normalized primary file into a new record after approval and file preflight. |
| Reference preservation | Reference-only legacy import | Preserve one lab-managed external source reference without source observation or storage mutation. |
| External file observation | Reference-only source observation | Check availability, sha256, and byte size for one preserved external source reference. |
| New-record writing | New-run writer, append-only storage writer | Represent writer events and write one new storage record from declared chunks. |
| Stored source observation | Measurement source observation | Observe one declared normalized primary-data file under storage and check fixture-level row count. |
| Handoff/package use | Handoff package route | Own package-local normalized data projection and open-before-import package use separately from legacy import. |

## Test And Fixture Posture

Future tests should prefer route behavior over restating every low-level
contract in every slice:

- keep one negative test for each new authority claim, such as copy approval,
  reference-only materialization, observed file facts, or data-level read;
- validate consumed fact projections at the boundary where they are consumed,
  but avoid replaying an entire previous slice unless that is the behavior
  being tested;
- keep repository fixtures small and repository-safe;
- do not make discovery expected outputs portable/public artifacts by default;
- do not duplicate contract-primitives tests unless a slice introduces a new
  semantic category or same-class field audit.

## Deferred Decisions

Keep these out of the current route until a named workflow requires them:

- stable public import API or adapter API;
- core LabRAD, DataVault, Labber, or lab-specific legacy readers;
- adapter package/drop-folder protocol, discovery, trust, and failure model;
- existing-record append/update, locking, crash recovery, merge, and conflict
  behavior;
- reference repair, moved-reference discovery, or automatic path search;
- data-level open/read of external references that are not normalized primary
  data;
- broad schema inference, automatic scan-shape inference, or generic dataframe
  semantics;
- GUI import/review workflow and user interaction states;
- linked-context payload import or recursive relation traversal;
- final storage schema, storage indexing, and shared measurement-record domain
  model.

## Reopen Triggers

Do more import/source-route work only when one of these concrete triggers
appears:

- Users need to drop an adapter-produced bundle into Scopecat:
  validate adapter package or drop-folder shape, required files, reviewed
  facts, and failure reporting.
- Users need to convert legacy data for plotting:
  validate data-level open/read of adapter-normalized output, not direct
  parsing of arbitrary legacy source references.
- Users need reference-only records to recover from moved files:
  validate a repair/review workflow without automatic path discovery by
  default.
- Users need to add data to existing records:
  validate append/update locking, crash recovery, conflict policy, and
  in-progress record semantics separately from new-record import.
- Two or more routes need identical measurement-record behavior with the same
  lifecycle and failure semantics:
  reconsider shared model extraction with an accepted decision.

## Recommended Next Work

The next high-value slice is **adapter package/drop-folder validation** if the
product question is how lab-owned adapters hand normalized data to Scopecat.
This is an adapter-produced input boundary, not the Scopecat-authored handoff
package route.

That slice should validate a small adapter-produced bundle with:

- explicit adapter identity and source identity;
- one normalized primary data item;
- one external source reference for provenance;
- declared preview metadata as an adapter assertion;
- small linked-context references;
- repository-safe findings for missing, malformed, or inconsistent required
  files.

It should not copy into storage, parse legacy source formats, infer schema,
repair references, define GUI behavior, or accept a stable public adapter API.

If the product question is instead durable storage editing, do
**existing-record append/update** next. That is a storage-concurrency and
mutation slice, not an import/source-reference slice.

## Stop Rule

Do not add another import/source slice merely to restate that external source
references are not previewable primary data, that file-level observation is not
data-level observation, or that adapters own legacy parsing. Future work should
name the user workflow and the authority boundary it changes.
