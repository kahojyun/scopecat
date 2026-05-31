# Parameter State Storage Writer Validation Plan

## Status

Validation plan, not an ADR.

This plan defines a narrow mutation slice for writing one reviewed managed
parameter-state summary under a caller-provided storage root. It does not
accept final storage architecture, legacy parameter parsers, schema migration,
external file authority, hardware write-back, GUI behavior, or shared domain
model extraction.

## Source Material

Compact source notes live under `<sample>/_research/`:

- `parameter-files-and-artifacts.md`;
- `parameter-mutation-workflows.md`;
- `parameter-lineage-schema-pressure.md`.

This slice follows
[`adapter-parameter-import-review-commit-validation-result.md`](adapter-parameter-import-review-commit-validation-result.md).
That review/commit slice validated side-effect-free conversion from adapter
preview into a managed parameter-state summary. This slice tests the next
boundary: approved local storage mutation for that reviewed summary.

It uses the low-level no-overwrite filesystem helper posture validated in
[`../support/filesystem-mutation-helpers-validation-result.md`](../support/filesystem-mutation-helpers-validation-result.md).

First fixture:

- `tests/fixtures/parameter_state_storage_writer/basic_write/`

## Validation Question

Can Scopecat write one reviewed managed parameter-state summary under a
caller-provided storage root using approved no-overwrite behavior, deterministic
manifest and receipt files, checksum facts, and preserved provenance, while
avoiding legacy parsing, schema migration, external file authority, and
hardware write-back?

## Evidence Pressure

The sample evidence supports this fixture boundary:

- current parameter states live in mutable files and copied variants, but
  Scopecat-managed parameter state needs a bounded storage path;
- adoption from adapter previews needs a durable handoff after review;
- provenance to adapter-declared legacy sources should be preserved without
  making those sources authoritative;
- storage mutation should be explicit, approved, no-overwrite, and separate
  from hardware mutation.

## First Fixture Shape

The first fixture should stay small:

- one reviewed managed parameter-state summary;
- one approved storage write request;
- one state directory under a caller-provided storage root;
- one deterministic parameter-state manifest file;
- one deterministic write receipt file;
- checksum and size facts for both written files;
- no-overwrite behavior for state directory, manifest, and receipt targets.

## Input Boundary

Fixture input may include:

- storage policy and approved write request;
- reviewed managed parameter-state identity, lineage, readiness, trust status,
  trusted entry paths, and entries;
- adapter/source provenance and excluded preview entries;
- side-effect claims;
- optional expected digest facts for deterministic validation.

Fixture input should not include:

- raw legacy source files;
- legacy JSON/XLSX parsing behavior;
- schema migration transforms;
- hardware state, hardware writes, or instrument write logs;
- external mutable file authority;
- GUI operations;
- final storage architecture.

## Expected Output

Expected review output should let a reviewer answer:

- which parameter state was written;
- which storage paths were written;
- which digests and sizes were observed for written files;
- that existing targets are refused;
- what provenance and excluded preview facts were preserved;
- why legacy parsing, schema migration, external authority, and hardware
  write-back remain out of scope.

## Out Of Scope

This plan does not earn:

- final storage architecture;
- legacy parameter parser;
- schema migration;
- external file authority;
- hardware write-back or instrument state tracking;
- GUI behavior;
- shared domain model extraction.

## Slice Recommendation

Stop this slice at bounded local storage writing. Later slices can validate
read views, storage catalog behavior, source observation, or prepared-run
consumption from stored parameter state without reopening legacy parsing or
hardware write-back.
