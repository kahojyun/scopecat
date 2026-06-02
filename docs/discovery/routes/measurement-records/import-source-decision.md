# Measurement Import And Source Route Decision Consolidation

## Status

Discovery decision consolidation, not an ADR.

This note closes the current measurement import/source-reference discovery
pass. It records the route decisions earned by the validated adapter-authored
legacy import, adapter output boundary, normalized primary table, legacy import
acceptance, reference-only import, reference-only source observation,
append-only storage writer, existing-record append receipt, and measurement
source observation slices.

Later durable Measurement Records import work supersedes the copy-acceptance
slice for active new-record import. Keep this document as discovery route
evidence for source/reference separation and historical copy acceptance; use
[`handoff-durable-import-storage.md`](../../../architecture/boundaries/handoff-durable-import-storage.md)
for the current durable new-record import boundary.

It does not accept a stable import API, adapter API, legacy reader, final
storage schema, full existing-record update behavior, reference repair,
package format, GUI contract, dataframe API, schema-inference engine, or
shared measurement-record domain model.

## Accepted For Now

The current route separates **legacy source**, **normalized primary data**,
and **observed file facts**:

```text
legacy system data
  -> user/lab adapter output
  -> reviewed adapter-produced boundary facts
  -> reviewed adapter-authored manifest
  -> choose copy acceptance or reference-only acceptance
  -> optionally observe file facts
  -> optionally read normalized primary table facts where the route needs them
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

The historical copy-acceptance slice owned one approved copy-into-new-record
mutation for reviewed adapter-normalized primary data. The copied file was
Scopecat-readable only because the adapter output was normalized, not because
the legacy source existed or was observed. Active new-record import now goes
through the durable Measurement Records creation, writer, finalization, and
read-model pipeline.

Stored source observation is a separate read-only check over a declared
normalized primary-data file under a caller-provided storage root. Its current
row-count check is data-level evidence for the validated normalized fixture,
not a generic schema inference engine.

Normalized primary table reading is the route's first shared data-level table
contract. It validates already-provided Scopecat-readable CSV bytes as
string-valued rows with declared preview-column bindings. It does not observe
files, parse legacy sources, infer schemas or dtypes, build plot series, or
define dataframe behavior. A consuming route can adopt this table read before
review/acceptance or after storage/package boundaries when that boundary
already has normalized table bytes and needs table facts.

Existing-record append receipt owns one approved append-style mutation under
an existing record directory. It first proves the existing record directory
without creating it, then uses a direct record-local lock guard before
current-record preflight, append-chunk read, and no-overwrite
append-segment/update-receipt writes. It records append evidence without
replacing the manifest, merging primary data, refreshing a read model, defining
lock identity, or accepting crash recovery.

Declared preview metadata from adapters is useful as an assertion. It becomes
Scopecat-observed previewability only when normalized data access or an
explicit adapter authority has been validated by the relevant slice.

The current adapter output boundary fixture is file-shaped only to make the
boundary testable. It does not decide whether the final adapter handoff is a
drop-folder protocol, writer-like API, service call, or another transport. The
stable part for now is the logical boundary: reviewed adapter manifest facts
plus declared output file facts.

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
| Adapter-produced input boundary | Adapter output boundary | Validate one file-shaped adapter-produced boundary as transport pressure, including declared manifest, primary-data, and linked-context file facts. |
| Normalized table reading | Normalized primary table | Validate already-provided normalized CSV bytes into string-valued table facts and declared preview rows without file observation or schema inference. |
| Copy acceptance | Legacy import acceptance | Historically copied one reviewed adapter-normalized primary file into a new record after approval and file preflight; active new-record import is owned by durable Measurement Records import. |
| Reference preservation | Reference-only legacy import | Preserve one lab-managed external source reference without source observation or storage mutation. |
| External file observation | Reference-only source observation | Check availability, sha256, and byte size for one preserved external source reference. |
| New-record writing | New-run writer, append-only storage writer | Represent writer events and write one new storage record from declared chunks. |
| Existing-record append receipt | Existing record append update | Record append evidence under an existing record directory with current-record preflight, direct record-local lock guard, and no-overwrite new update files. |
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
- final adapter package/drop-folder protocol, writer-like adapter API,
  discovery, trust, and failure model beyond the current logical boundary;
- stronger existing-record update behavior such as manifest replacement,
  primary-data merge or compaction, read-model refresh, lock identity,
  stale-lock cleanup, crash recovery, and conflict policy;
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
  extend the current adapter output boundary into a concrete final transport,
  discovery, trust, and failure model.
- Users need to convert legacy data for plotting:
  first require normalized Scopecat-readable table bytes, then use or extend
  normalized table reading rather than parsing arbitrary legacy references.
- Users need reference-only records to recover from moved files:
  validate a repair/review workflow without automatic path discovery by
  default.
- Users need to add data to existing records:
  validate stronger update behavior such as manifest replacement, read-model
  refresh, stale-lock cleanup, crash recovery, conflict policy, and in-progress
  record semantics separately from the first append-receipt slice.
- Two or more routes need identical measurement-record behavior with the same
  lifecycle and failure semantics:
  reconsider shared model extraction with an accepted decision.

## Recommended Next Work

The first adapter-produced input boundary is now validated in
[`adapter-output-boundary-validation-result.md`](../../slices/measurement-records/adapter-output-boundary-validation-result.md).
Do more work on this track only when a product workflow needs a concrete final
adapter handoff mechanism, such as drop-folder discovery, a writer-like API, or
service-mediated adapter output.

The first data-level normalized table read is now validated in
[`normalized-primary-table-validation-result.md`](../../slices/measurement-records/normalized-primary-table-validation-result.md).
Adopt it in adapter output, storage observation, handoff package, SDK, or GUI
routes only when that route needs the same table behavior.

If the product question is instead durable storage editing beyond append
receipts, validate the next existing-record update boundary: manifest
replacement, read-model refresh, stale-lock cleanup, crash recovery, conflict
policy, or in-progress record semantics. That remains storage-concurrency and
mutation work, not import/source-reference work.

## Stop Rule

Do not add another import/source slice merely to restate that external source
references are not previewable primary data, that file-level observation is not
data-level observation, or that adapters own legacy parsing. Future work should
name the user workflow and the authority boundary it changes.
