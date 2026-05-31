# Adapter-Authored Parameter State Import Preview Validation Plan

## Status

Validation plan, not an ADR.

This plan defines a narrow parameter-state slice for previewing normalized
parameter-state import manifests authored by user-owned adapters. It does not
accept a stable public adapter API, legacy `parameters.json` reader, XLSX
parameter table reader, project-specific parser, import acceptance,
Scopecat-managed parameter-state creation, schema migration, external file
authority, hardware write-back, GUI behavior, or shared domain model
extraction.

## Source Material

Compact source notes live under `<sample>/_research/`:

- `parameter-files-and-artifacts.md`;
- `parameter-mutation-workflows.md`;
- `parameter-lineage-schema-pressure.md`.

This slice follows the same boundary posture as the Measurement Records
adapter-authored legacy import slice:
[`../measurement-records/adapter-authored-legacy-import-validation-result.md`](../measurement-records/adapter-authored-legacy-import-validation-result.md).

The fixture represents adapter output, not raw legacy parameter input. A
user-owned adapter has already parsed legacy parameter JSON, XLSX tables, or
project-specific outputs and emitted a normalized Scopecat-shaped manifest.
Scopecat consumes that manifest for review without supporting those legacy
formats directly.

First fixture:

- `tests/fixtures/adapter_authored_parameter_state_import_preview/json_and_xlsx_sources/`

## Validation Question

Can Scopecat preview an adapter-authored parameter-state import manifest while
keeping legacy JSON/XLSX parsing in user-owned adapters, preserving declared
source identity and candidate entries, and avoiding import acceptance,
managed-state creation, schema migration, external file authority, and hardware
write-back?

## Evidence Pressure

The sample evidence supports this fixture boundary:

- current parameter workflows use active JSON files, copied variants, table
  companions, and project-specific outputs;
- legacy parameter sources are not one stable format that Scopecat can parse
  generically;
- XLSX or table-shaped parameter companions carry schema pressure that should
  not be silently flattened;
- adapter-owned normalization lets labs bridge current formats without making
  those formats Scopecat core behavior.

## First Fixture Shape

The first fixture should stay small:

- one adapter identity with external parsing authority;
- two declared legacy sources, one JSON-shaped and one XLSX-shaped;
- one candidate parameter-state preview with lineage, readiness, and trust
  hints;
- two scalar candidate entries;
- one untrusted carried value skipped from candidate entries;
- one schema-limited table-shaped value skipped from candidate entries;
- adapter findings that state legacy parsing happened outside Scopecat core.

## Input Boundary

Fixture input may include:

- adapter identity, version, source-system detail, and parsing authority;
- legacy source identities with public-safe redacted display paths, source
  format labels, adapter-declared availability, and redacted local-path state;
- candidate parameter-state metadata such as lineage hints, readiness hints,
  and trust hints;
- normalized candidate entries with path, label, scalar value, unit, trust,
  value shape, and source references;
- skipped entries with source references and reasons;
- adapter findings.

Fixture input should not include:

- raw legacy parameter JSON parsing behavior;
- raw XLSX parsing behavior;
- project-specific parser behavior;
- file reads or checksum verification;
- accepted Scopecat-managed parameter state;
- schema migration transforms;
- hardware state, hardware writes, or instrument write logs;
- GUI operations;
- stable public adapter API.

## Expected Output

Expected review output should let a reviewer answer:

- which adapter authored the manifest;
- which legacy sources were declared and what formats they represent;
- which candidate entries could be reviewed for future managed state;
- which values were skipped as untrusted or schema-limited;
- why Scopecat did not parse the legacy files;
- why no parameter state was created, no import was accepted, no schema
  migration ran, and no hardware write-back occurred.

## Out Of Scope

This plan does not earn:

- stable public adapter API;
- legacy `parameters.json` reader;
- XLSX parameter table reader;
- project-specific parser support in Scopecat core;
- import acceptance;
- Scopecat-managed parameter-state creation;
- schema migration;
- external file authority;
- hardware write-back or instrument state tracking;
- GUI behavior;
- shared domain model extraction.

## Slice Recommendation

Stop this slice at adapter-authored import preview. Later slices can validate
review/commit of a previewed candidate into Scopecat-managed parameter state,
source observation, or concrete adapter transport without adding legacy parsers
to Scopecat core.
