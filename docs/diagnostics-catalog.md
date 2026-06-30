# Diagnostics Catalog

Status: initial core catalog
Date: 2026-06-29

This catalog records stable core diagnostic codes that are asserted by tests or
may appear in boundary records. It is intentionally doc-backed first: emission
stays local to each subsystem, while tests use catalog-aware helpers for codes
whose stability matters.

## Entry Fields

- `code`: stable diagnostic code.
- `owner`: subsystem that emits the code.
- `family`: product area or record boundary.
- `severity`: default severity.
- `stability`: `stable`, `domain-stable`, `internal`, or `deprecated`.
- `path`: expected logical path shape.
- `persisted`: whether the code may appear in persisted boundary records.

## Run Comparison

| code | owner | family | severity | stability | path | persisted | description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `run_comparison_invalid_id` | core.run_comparison | run_comparison | error | stable | request field | no | Run or observable selector is not a safe id. |
| `unsupported_run_comparison_input` | core.run_comparison | run_comparison | error | stable | runner/input kind | no | Run comparison received a run type it cannot compare. |
| `missing_run_comparison_input` | core.run_comparison | run_comparison | error | stable | measurement artifact | no | Required measurement data is missing. |
| `empty_run_comparison_input` | core.run_comparison | run_comparison | error | stable | measurement artifact | no | Measurement data artifact has no records. |
| `invalid_run_comparison_input` | core.run_comparison | run_comparison | error | stable | measurement artifact | no | Measurement data could not be decoded or validated. |
| `run_comparison_measurement_mismatch` | core.run_comparison | run_comparison | error | stable | measurement records | no | Baseline and candidate measurement counts differ. |
| `run_comparison_point_mismatch` | core.run_comparison | run_comparison | error | stable | measurement record point | no | Baseline and candidate point ids or indexes differ. |
| `run_comparison_missing_observable` | core.run_comparison | run_comparison | error | stable | observable id | no | Expected observable is missing from one side. |
| `run_comparison_unit_mismatch` | core.run_comparison | run_comparison | error | stable | observable unit | no | Compared observable units differ. |
| `missing_run_comparison_dataset_schema` | core.run_comparison | run_comparison | error | stable | measurement artifact metadata | no | Raw measurement artifact lacks dataset schema metadata. |
| `run_comparison_ambiguous_primary_observable` | core.run_comparison | run_comparison | error | stable | dataset schema | no | Multiple primary observables require an explicit observable selector. |
| `run_comparison_primary_observable_mismatch` | core.run_comparison | run_comparison | error | stable | dataset schema | no | Baseline and candidate primary observables do not match. |
| `run_comparison_already_reviewed` | core.run_comparison | run_comparison_review | error | stable | comparison | no | Review was attempted for an already reviewed comparison. |
| `run_comparison_not_found` | core.run_comparison | run_comparison_review | error | stable | selector | no | Requested comparison artifact was not found. |
| `run_comparison_path_escape` | core.run_comparison | run_comparison_review | error | stable | selector | no | Comparison selector escaped the run directory. |
| `run_comparison_is_directory` | core.run_comparison | run_comparison_review | error | stable | selector | no | Comparison selector resolved to a directory. |
| `invalid_run_comparison` | core.run_comparison | run_comparison_review | error | stable | comparison artifact | no | Comparison artifact content or kind is invalid. |
| `unsupported_run_comparison_review_state` | core.run_comparison | run_comparison_review | error | stable | state | no | Review state is outside the accepted state set. |

## Reporting And Artifact Access

| code | owner | family | severity | stability | path | persisted | description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `missing_report_input` | core.reporting | reporting | error | stable | report input | no | Required report input is missing. |
| `invalid_report_input` | core.reporting | reporting | error | stable | report input | no | Report input exists but is invalid for rendering. |
| `artifact_path_escape` | core.storage | artifact | error | stable | artifact path | no | Artifact path escapes the run storage root. |
| `report_artifact_is_directory` | core.reporting | reporting | error | stable | artifact path | no | Report artifact path points to a directory. |

## Analysis And Candidate Config

| code | owner | family | severity | stability | path | persisted | description |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `analysis_note_invalid` | core.session | analysis | error | stable | content | no | Notebook analysis note content is empty. |
| `analysis_external_ref_invalid` | core.session | analysis | error | stable | uri | no | Notebook analysis external reference URI is empty. |
| `analysis_guess_parameter_invalid` | core.session | analysis | error | stable | parameter_id | no | Analysis parameter guess has an empty parameter id. |
| `analysis_guess_confidence_invalid` | core.session | analysis | error | stable | confidence | no | Analysis parameter guess confidence is outside `[0, 1]`. |
| `run_handle_manifest_missing` | core.session | run_handle | error | stable | run | no | Run handle construction did not receive a manifest or run result. |
| `run_execution_snapshot_not_loaded` | core.session | run_handle | error | stable | run | no | Operation requires an execution result that was not loaded. |

## Catalog Maintenance

Add codes here when tests start treating them as stable behavior, when they can
appear in persisted records, or when another package needs to depend on their
meaning. Test-only `test_*` and `fake_*` codes stay out of this product catalog.
