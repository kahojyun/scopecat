# Source-Agnostic Parameter-State Read View Validation Plan

## Status

Validation plan, not an ADR.

This plan defines a narrow read-only slice for explicit stored parameter-state
references across adapter-derived and calibration-derived storage manifests.
It does not accept final storage architecture, catalog discovery, storage
mutation, compatibility output, hardware write-back, schema migration, GUI
behavior, a universal provenance schema, or shared domain model extraction.

## Source Material

This slice follows:

- [`parameter-state-storage-read-view-validation-result.md`](parameter-state-storage-read-view-validation-result.md)
- [`calibration-parameter-state-storage-validation-result.md`](calibration-parameter-state-storage-validation-result.md)
- [`parameter-state-storage-writer-validation-result.md`](parameter-state-storage-writer-validation-result.md)

The existing read view validates explicit reads for adapter-derived storage.
The calibration-derived storage slice deliberately preserves calibration
handoff provenance rather than forcing it into adapter/legacy-source fields.
This slice tests whether both stored shapes can share one consumption surface
for common state facts while keeping provenance typed.

First fixture:

- `tests/fixtures/source_agnostic_parameter_state_read_view/basic_read/`

## Validation Question

Can Scopecat read explicit adapter-derived and calibration-derived stored
parameter-state manifest/receipt pairs through one read-only surface,
validating checksum and receipt continuity while projecting common state facts
and preserving source-specific provenance as typed payloads?

## Evidence Pressure

The current storage evidence has two source families:

- adapter-derived storage with adapter and legacy-source provenance;
- calibration-derived storage with handoff, step, observation, and review
  provenance.

A prepared run, review surface, or future catalog should not need different
read APIs for basic state identity, lineage, trusted entries, observed file
facts, and receipt continuity. At the same time, collapsing provenance too
early would erase important owner boundaries.

## First Fixture Shape

The first fixture should include:

- one explicit adapter-derived stored parameter-state reference;
- one explicit calibration-derived stored parameter-state reference;
- expected sha256 and byte-size facts for each manifest and receipt;
- common projection of state id, kind, label, lineage, readiness, trust status,
  trusted entry paths, and trusted entries;
- typed provenance payloads for adapter import and calibration handoff;
- review findings for unavailable or mismatched explicit files.

The fixture should not include:

- storage catalog or index discovery;
- writes, repairs, migrations, or manifest rewriting;
- compatibility output;
- hardware state, hardware writes, or instrument logs;
- source payload reads beyond the declared manifest/receipt files;
- GUI operations.

## Expected Output

Expected review output should let a reviewer answer:

- which stored parameter states were explicitly read;
- whether adapter-derived and calibration-derived manifests were both observed;
- whether sha256, byte-size, and receipt facts are continuous;
- which common state facts are available across source families;
- which source-specific provenance payloads remain attached;
- why the read view does not imply catalog discovery, storage mutation,
  compatibility output, hardware write-back, schema migration, or a universal
  provenance schema.

## Out Of Scope

This plan does not earn:

- final storage architecture;
- storage catalog or index discovery;
- storage mutation, repair, or migration;
- compatibility output;
- hardware write-back or current instrument state;
- universal provenance schema;
- GUI behavior;
- shared domain model extraction.

## Slice Recommendation

Stop this slice at explicit source-agnostic read projection. Catalog discovery,
compatibility output, and hardware apply should remain separate follow-ups.
