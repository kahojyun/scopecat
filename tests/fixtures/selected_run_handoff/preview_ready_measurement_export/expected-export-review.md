# Expected Preview-Ready Measurement Export Review

## Fixture Wrapper

- expected output id: `preview-ready-measurement-export.expected`
- status: `expected_validation_output`
- source fixture: `export-input.json`
- reference semantics: `fixture_paths_are_package_relative`
- guard: This expected output is not a final package format, schema contract, storage layout, or path-addressed identity model.

Fixture `path` and `source_file` values are package-relative materialized test
files. They are not the final storage identity model.

## Candidate Summary Review

### Selected Export Set

- selection mode: `multi_measurement`
- selected measurements: `1001`, `1002`
- traversal policy: `non_recursive`

Selecting these measurements exports their default source/metadata bundles.
Linked files are reported with declared inclusion status and are not recursively
traversed.

### Included By Default

| Measurement | Experiment | Included items |
| --- | --- | --- |
| `1001` | qA Rabi amplitude sweep | Run 1001 Rabi source data (`source/export-demo-session/measurement-1001-rabi-source.csv`); Run 1001 parameter snapshot (`snapshots/measurement-1001-parameter-snapshot.json`) |
| `1002` | qA T1 decay | Run 1002 T1 source data (`source/export-demo-session/measurement-1002-t1-source.csv`); Run 1002 parameter snapshot (`snapshots/measurement-1002-parameter-snapshot.json`) |

### User-Included Optional Context

- Session wiring note (`attachments/export-session-wiring-note.md`): `attachment`; relation `documents`; authority `user_declared`; linked measurements `1001`, `1002`.

### Visible But Excluded Optional Context

- qA summary candidate (`artifacts/optional-two-measurement-summary.csv`): `artifact`; relation `summarizes`; authority `user_declared`; linked measurements `1001`, `1002`.

The excluded artifact is visible so a user can decide whether to include it in
a later export. This fixture does not treat it as proof of analysis lineage.

### Missing Context

- Measurement 1002 fit note (`attachments/measurement-1002-fit-note.md`): `attachment`; relation `documents`; authority `user_declared`; linked measurements `1002`.

### Preview Readiness

| Measurement | Status | Shape | Declared roles | Plot candidates | Warning |
| --- | --- | --- | --- | --- | --- |
| `1001` | `preview_ready` | `1d_multi_response_table` | `drive_amp` sweep axis; `iq_i` measured response; `iq_q` measured response; `bias_v` held condition | `drive_amp` -> `iq_i`; `drive_amp` -> `iq_q` | none |
| `1002` | `degraded_preview` | `none` | none | none | preview_metadata_missing |

Preview readiness supports later export-side selection and import-side
confirmation. It is not rendered plotting, fit validation, uncertainty,
reproducibility, or scientific validation. Missing preview metadata degrades the
preview surface but does not block export when source identity and primary data
are present.

The fixture intentionally does not infer preview roles from measurement `1002`
CSV headers.

### Source Recovery And Data Handling

- public-safe source location: `LAB_LOCAL:/redacted/datavault/export-demo-session`
- local source path is redaction-sensitive and not portable.
- selected source data should not be silently compressed, converted, filtered,
  or replaced by a derived copy during export.
- source provenance:
  - `1001`: `LAB_LOCAL:/redacted/datavault/export-demo-session/measurement-1001-rabi-source.csv`; data handling `no_silent_transform`.
  - `1002`: `LAB_LOCAL:/redacted/datavault/export-demo-session/measurement-1002-t1-source.csv`; data handling `no_silent_transform`.

### Warnings

- `local_only_path`: Original local path is redaction-sensitive and not portable.
- `preview_metadata_missing`: Measurement 1002 can still be exported, but preview shape and column roles are missing.
- `missing_companion`: A user-declared companion for measurement 1002 is absent from the fixture.

## Boundary Notes

- normal source data handling is represented as `source_transform_policy`, not
  as a warning.
- visible-but-excluded linked context is represented by `include_status`, not
  as a warning.
- non-recursive traversal is represented by `traversal_policy`, not as a
  warning.
- this review is not claiming analysis lineage, fit validity, scientific
  validity, or reproducibility.

## Reviewer Questions

A reviewer should be able to answer:

- which measurements were intentionally selected;
- which primary data and metadata are included by default;
- which optional linked file was included by user choice;
- which optional linked file is visible but excluded;
- which preview metadata is ready and which measurement has degraded preview;
- which source files should not be silently transformed;
- which context is missing;
- that Scopecat is not claiming a downstream analysis DAG or scientific
  validation.
