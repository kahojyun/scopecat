# Adapter Parameter Import Review Commit Validation Plan

## Status

Validation plan, not an ADR.

This plan defines a narrow parameter-state slice for reviewing an
adapter-authored parameter import preview and creating a managed parameter
state summary from explicitly accepted candidate entries. It does not accept a
legacy parser, stable public adapter API, storage writer, schema migration,
external file authority, hardware write-back, GUI behavior, or shared domain
model extraction.

## Source Material

Compact source notes live under `<sample>/_research/`:

- `parameter-files-and-artifacts.md`;
- `parameter-mutation-workflows.md`;
- `parameter-lineage-schema-pressure.md`.

This slice follows
[`adapter-authored-parameter-state-import-preview-validation-result.md`](adapter-authored-parameter-state-import-preview-validation-result.md).
That preview slice validated normalized adapter-authored parameter manifests
without parsing legacy JSON/XLSX sources or creating managed parameter state.
This slice tests the next boundary: an explicit review accepts selected
candidate entries and produces a managed parameter-state summary while keeping
skipped preview entries excluded.

First fixture:

- `tests/fixtures/adapter_parameter_import_review_commit/basic_review_commit/`

## Validation Question

Can Scopecat convert an adapter-authored parameter import preview into a
managed parameter-state summary through explicit review, accepting only
reviewed candidate entries while preserving adapter/source provenance and
avoiding legacy parsing, schema migration, external file authority, storage
mutation, and hardware write-back?

## Evidence Pressure

The sample evidence supports this fixture boundary:

- labs need adoption paths from legacy JSON, XLSX tables, and project-specific
  parameter outputs into first-class parameter state;
- adapter previews can normalize candidate entries, but human review should
  decide what becomes managed state;
- untrusted copied values and table-shaped schema-limited values should remain
  visible without being silently committed;
- managed parameter state should preserve provenance to adapter-declared
  sources without making those sources authoritative.

## First Fixture Shape

The first fixture should stay small:

- one adapter-authored import preview manifest;
- one accepted review decision;
- two accepted scalar candidate entries;
- two rejected or deferred preview entries;
- one managed seed parameter-state summary with accepted entries only;
- adapter and legacy-source provenance preserved as adapter-declared facts;
- explicit side-effect claims that parsing, migration, external authority,
  storage mutation, and hardware write-back were not performed.

## Input Boundary

Fixture input may include:

- the adapter-authored preview manifest;
- review identity, status, accepted time, reviewer role, accepted entry paths,
  and rejected/deferred entry paths;
- managed parameter-state identity, lineage, readiness, trust status, trusted
  entry paths, accepted entries, and review/provenance references;
- side-effect claims.

Fixture input should not include:

- raw legacy parameter parsing behavior;
- file writes or storage mutation;
- schema migration transforms;
- hardware state, hardware writes, or instrument write logs;
- external file authority;
- GUI operations;
- stable public adapter API.

## Expected Output

Expected review output should let a reviewer answer:

- which adapter preview was reviewed;
- which candidate entries were accepted;
- which preview entries remain excluded;
- which managed parameter-state summary resulted;
- which adapter and source references provide provenance;
- why no legacy parsing, schema migration, storage mutation, external file
  authority, or hardware write-back occurred.

## Out Of Scope

This plan does not earn:

- legacy parameter parser;
- stable public adapter API;
- storage writer;
- schema migration;
- external file authority;
- hardware write-back or instrument state tracking;
- GUI behavior;
- shared domain model extraction.

## Slice Recommendation

Stop this slice at side-effect-free review/commit summary. A later mutation
slice can validate writing managed parameter state to storage if that becomes
necessary, but should start from this reviewed summary rather than reopening
legacy parsing.
