# Calibration Parameter-State Storage Validation Plan

## Status

Validation plan, not an ADR.

This plan defines a narrow parameter-state storage slice for writing a
calibration-derived managed parameter-state summary after explicit storage
approval. It does not accept final storage architecture, general read-view
compatibility, compatibility output, hardware write-back, rollback,
calibration execution, GUI behavior, or shared domain model extraction.

## Source Material

This slice follows:

- [`calibration-parameter-state-intake-validation-result.md`](calibration-parameter-state-intake-validation-result.md)
- [`parameter-state-storage-writer-validation-result.md`](parameter-state-storage-writer-validation-result.md)
- [`../support/filesystem-mutation-helpers-validation-result.md`](../support/filesystem-mutation-helpers-validation-result.md)

The existing parameter-state storage writer validates bounded no-overwrite
storage for adapter-derived managed states. This slice tests the adjacent
pressure case: a calibration-derived managed state should be storable without
pretending calibration handoff provenance is adapter or legacy-source
provenance.

First fixture:

- `tests/fixtures/calibration_parameter_state_storage/basic_write/`

## Validation Question

Can Scopecat write a calibration-derived parameter-state intake summary to a
caller-provided storage root through an approved no-overwrite request while
preserving calibration handoff provenance and avoiding compatibility output,
hardware write-back, rollback, calibration execution, and final storage-schema
claims?

## Evidence Pressure

The validated intake slice proves parameter-state management can project a
managed state summary from an accepted calibration handoff. The next practical
question is whether that managed state can cross the same local persistence
boundary as adapter-derived parameter states while keeping provenance explicit:

- adapter-derived storage preserves adapter and legacy-source references;
- calibration-derived storage should preserve handoff, step, observation, and
  review identities;
- storage approval and no-overwrite filesystem behavior are still required;
- storage should not imply compatibility-file emission or instrument apply.

## First Fixture Shape

The first fixture should include:

- one nested calibration parameter-state intake input;
- one approved storage request with declared relative state directory,
  manifest path, and receipt path;
- deterministic expected digest facts for the written manifest and receipt;
- side-effect claims that storage mutation is performed while compatibility
  output, hardware write-back, rollback, and calibration execution are not.

The fixture should not include:

- adapter or legacy-source provenance fields;
- storage catalog discovery;
- read-view consumption;
- compatibility output;
- hardware state, hardware writes, or instrument logs;
- rollback instructions;
- calibration or measurement payload execution;
- GUI operations.

## Expected Output

Expected review output should let a reviewer answer:

- which calibration-derived parameter state was written;
- which intake review and handoff identities were preserved;
- which manifest and receipt paths were written;
- which bytes and sha256 digests were observed;
- what no-overwrite boundary was enforced;
- why storage does not imply compatibility output, hardware write-back,
  rollback, calibration execution, or final storage architecture.

## Out Of Scope

This plan does not earn:

- final storage architecture;
- general parameter-state storage schema;
- storage read-view compatibility;
- compatibility output;
- hardware write-back or current instrument state;
- rollback contract;
- calibration or measurement execution;
- shared relation graph;
- GUI behavior;
- shared domain model extraction.

## Slice Recommendation

Stop this slice at bounded storage of calibration-derived parameter-state
summaries. A later source-agnostic storage/read-view slice can decide whether
adapter-derived and calibration-derived manifests should converge.
