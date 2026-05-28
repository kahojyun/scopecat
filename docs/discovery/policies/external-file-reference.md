# External File Reference Policy

## Status

Discovery policy sketch, not an ADR.

This note records candidate vocabulary and unresolved policy questions for
externally referenced files. It does not accept a final storage architecture,
backup model, checksum contract, file watcher, importer, package format, or
general-purpose data management policy.

## Context

Selected measurement export and storage-transition fixtures now distinguish:

- source identity;
- current reference before export;
- export materialization path;
- managed Scopecat data;
- lab-managed network references;
- missing or moved external linked context.

That still does not decide how Scopecat should treat externally referenced
files over time.

This note should be read with
[`policies/artifact-boundary-and-redaction.md`](artifact-boundary-and-redaction.md):
discovery fixtures and expected outputs are repository-safe artifacts by
default, while portable/public/export artifacts and package writer outputs need
explicit portable/export redaction and reference rules.

The current product assumption is:

- Scopecat is not a general backup system;
- external references default to the latest externally managed state;
- original measurement data should not change silently after recording;
- at least lightweight observed file state, such as checksum, size, and
  timestamp, may be needed to detect meaningful changes;
- managed append-only measurement data has different needs from externally
  mutable files.

## Candidate Modes

These modes are analysis vocabulary, not accepted schema.

| Mode | Candidate meaning | Provenance strength |
| --- | --- | --- |
| `managed_copy` | Scopecat stores or owns the file content. | Stronger durability; exact guarantees still undecided. |
| `external_live_reference` | Scopecat records where a file is and how it relates to a measurement or artifact, but reads the latest external state. | Weak provenance; file may change or disappear. |
| `external_materialized_for_export` | An available external file is copied into an export package at export time. | Point-in-time portability for that package; does not imply Scopecat can restore earlier versions. |
| `external_snapshot` | Scopecat records or copies a point-in-time state for stricter provenance. | Stronger provenance if content or checksums are retained; not yet earned. |
| `observed_file_state` | Scopecat records lightweight metadata about a file observation, such as checksum, size, mtime, source identity, and observation time. | Detects drift between observations; not a backup unless content is copied. |

## Measurement Data Change Posture

Original measurement data has stronger expectations than ordinary notes or
scratch artifacts.

If original measurement data changes after Scopecat records or observes it,
that should be visible as an attention-worthy state. The minimum useful record
is likely an observed file state with checksum-like evidence, but the exact
algorithm, timing, and storage cost are not yet decided.

This does not mean every externally referenced file is immutable. A user may
legitimately want Scopecat to record a relationship to a file that continues to
change elsewhere. That mode can be useful for notes, evolving artifacts, or lab
file-management policies. It should not be confused with strict provenance.

## Managed Append-Only Data

Scopecat-managed measurement data may be append-only while a measurement is
running. That should not automatically require a full checksum history for
every intermediate append.

The likely distinction is:

- normal append/progress state while recording is active;
- final or checkpointed observed state after a meaningful boundary;
- unexpected mutation after finalization or after a recorded observation.

The exact checkpoint policy is not decided. It should be designed with the
running measurement inspection slice, storage implementation, and export
integrity expectations rather than inferred from this note alone.

## Not Backup

Recording checksums, sizes, mtimes, source identities, or observation times
does not mean Scopecat can restore old file contents.

Restoration requires an explicit copied snapshot, managed storage copy, archive,
or backup integration. None of those are accepted by this note.

## Current Questions

- Should `external_live_reference` be allowed for primary measurement data, or
  only for attachments, artifacts, notes, and lab-managed secondary files?
- If a primary measurement external reference changes, should Scopecat warn,
  block export, create a new observed state, or ask the user to classify the
  change?
- Which observed file state fields are the minimum useful set: checksum, size,
  mtime, source identity, file type, observation time, or something else?
- When should managed append-only data record checksums: per chunk, per
  checkpoint, on completion, on export, or only on demand?
- Should export always be point-in-time materialization, even for live external
  references?
- How should users distinguish "latest external state" from "recorded
  point-in-time state" in the GUI?

## Slice Recommendation

Carry these modes forward as policy vocabulary. Do not implement a checksum
contract, file watcher, backup feature, or shared storage model until a
concrete storage/export/import task needs it.
