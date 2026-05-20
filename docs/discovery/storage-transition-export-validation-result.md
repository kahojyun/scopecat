# Storage Transition Export Validation Result

## Status

Fixture validation result.

This is not an ADR, storage architecture, package format, checksum contract,
backup policy, importer design, GUI design, or shared domain model.

## Inputs

- [`storage-transition-export-fixture.md`](storage-transition-export-fixture.md)
- [`external-file-reference-policy.md`](external-file-reference-policy.md)
- `tests/fixtures/selected_run_handoff/storage_transition_export/`

## Validated Boundary

The storage-transition fixture clarified a narrow export-facing boundary:

- fixture input represents pre-export record/reference state;
- package materialization paths are expected export or planner output, not
  source input;
- source identity, current reference, and package materialization path are
  separate concepts;
- managed Scopecat data can use user-facing IDs or labels without exposing
  internal filesystem paths;
- lab-managed network references are the main external-reference pressure for
  this slice;
- available selected network data should be materialized into the export
  package for portability;
- missing or moved external linked context should be visible as a warning but
  should not automatically block export;
- package-relative fixture paths can support openability checks without
  becoming durable record identity.

## Domain Review Changes

The review changed the fixture interpretation in several important ways:

- arbitrary local-file reference mode should not be the default transition
  story;
- network or lab-managed locations may be either adoption pressure or a real
  lab file-management policy;
- users may legitimately want to record relationships to files that continue to
  change elsewhere, but that is weaker provenance;
- original measurement data has stronger expectations than notes, scratch
  artifacts, or evolving analysis files;
- if original measurement data changes after recording or observation, the
  change should not be silent;
- Scopecat should not imply it can restore old file contents unless it has
  explicitly copied, snapshotted, archived, or otherwise stored them.

## Candidate Vocabulary To Carry Forward

These terms are useful for future design but are not accepted schema:

| Term | Current meaning |
| --- | --- |
| `managed_copy` | Scopecat stores or owns the file content. |
| `external_live_reference` | Scopecat records a relationship to an external file and reads the latest externally managed state. |
| `external_materialized_for_export` | Scopecat copies available external content into an export package at export time. |
| `external_snapshot` | Scopecat captures a point-in-time file state for stronger provenance. |
| `observed_file_state` | Lightweight observation metadata such as checksum, size, mtime, source identity, and observation time. |
| `package_materialization_path` | Export/planner output path inside a package; not pre-export source state or durable identity. |

## Remaining Questions

- Should `external_live_reference` be allowed for primary measurement data, or
  only for attachments, artifacts, notes, and lab-managed secondary files?
- What minimum observed file state is needed for original measurement data:
  checksum, size, mtime, file type, observation time, or something else?
- Should changed original measurement data warn, block export, create a new
  observed state, or ask for user classification?
- How should managed append-only measurement data distinguish normal progress
  from unexpected mutation after finalization?
- When should export compute or validate observed file state?
- How should the GUI distinguish latest external state from recorded
  point-in-time state?

## Not Earned

This result does not earn:

- final storage architecture;
- final object ID, backend handle, or filesystem layout;
- final external-reference policy;
- checksum, observed-file-state, file-watcher, or integrity contract;
- backup, restore, archive, or snapshot behavior;
- package writer or importer behavior;
- export/import GUI;
- automatic repair for moved external paths;
- recursive relation traversal;
- shared domain model extraction.

## Current Recommendation

Stop this slice at fixture validation.

Carry forward the source/current-reference/materialization split and the
external-file policy vocabulary. Do not implement storage, checksum, backup,
package writer, importer, or GUI behavior until a concrete task needs one of
those boundaries.
