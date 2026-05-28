# Storage Transition Export Fixture

## Status

Fixture validation note, not an ADR.

This note records one early-adoption pressure case for selected measurement
export. It does not accept a final storage architecture, package format,
schema contract, object identity model, external-reference policy, importer,
or GUI workflow.

The fixture input models pre-export record/reference state. Package
materialization paths are expected output of export planning or packaging, not
source input.

## Inputs

- [`selected-measurement-export-decision-summary.md`](selected-measurement-export-decision-summary.md)
- [`preview-ready-selected-measurement-export-validation-result.md`](preview-ready-selected-measurement-export-validation-result.md)
- [`policies/external-file-reference.md`](../../policies/external-file-reference.md)
- `tests/fixtures/selected_run_handoff/storage_transition_export/`

## Why This Fixture Exists

Earlier selected measurement export fixtures use package-relative paths so the
expected files can be opened in tests. That is useful, but it can make `path`
look more durable than intended.

This fixture makes the storage transition pressure explicit:

- one selected measurement is already Scopecat-managed;
- one selected measurement still references lab-managed network source data;
- both available selected measurements are materialized into package-relative
  export paths;
- source identity remains recoverable after materialization;
- a user-labeled linked attachment can be included;
- a user-declared external artifact can be missing or moved;
- missing external context is warning-worthy;
- lab-managed network source data that is available for export is normal state,
  not a warning.
- arbitrary mutable local-file reference mode is not encouraged by this
  fixture.

## Candidate Distinctions

The fixture carries three separate references for selected data:

| Concept | Meaning In This Fixture |
| --- | --- |
| Source identity | Recoverable provenance for where the measurement came from. |
| Current reference | The reference Scopecat would use before export. It may be a managed object reference or a lab-managed network location. |
| Package materialization path | The package-relative file produced by export planning or packaging for export/openability checks. It is expected output, not pre-export input, and is not durable record identity. |

The same distinction is applied to linked context where useful. A managed
attachment can have a managed current reference and later package
materialization path. A missing network artifact can have recoverable source
identity but no package materialization path.

## What This Helps Later

This fixture should help future export/import and storage design ask better
questions before implementation:

- Can Scopecat record lab-managed network files without immediately ingesting
  them?
- If yes, is that temporary adoption support, lab file-policy support, or a
  normal supported mode?
- When export sees available network source data, should it materialize that
  data into the package by default?
- What should managed Scopecat data expose to users: labels and IDs, package
  paths, backend handles, or something else?
- What should happen when a user-declared external attachment or artifact is
  missing or moved?
- Should arbitrary mutable local-file reference mode be avoided, warned on, or
  supported only as an import source?
- If external references default to latest state, what observed file state is
  needed to make original measurement data changes visible?

## Still Not Earned

This fixture does not earn:

- final storage architecture;
- final object ID, backend handle, or filesystem layout;
- final external-reference policy;
- package writer or importer behavior;
- archive, checksum, or integrity contract;
- GUI copy/import workflow;
- automatic repair for moved external paths;
- recursive relation traversal;
- shared domain model extraction.

## Slice Recommendation

Keep this fixture as storage-transition pressure for later design. Do not
extend the selected measurement export implementation candidate from this case
unless the next task needs executable behavior around source identity, current
reference, and package materialization.
