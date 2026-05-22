# Managed Code Version Review

## Fixture

- Source: `managed-code-version-input.json`
- Boundary: managed code version record
- Status: fixture output, not product contract

## Managed Version

- Version: `managed-code-version-readout-0001`
- Source record: `code-snapshot-record-0001`
- Stable ID: `sc-codever-readout-0001`
- Storage authority: `scopecat_managed_record`
- Files: 3
- Notebook files: 2

## File Inventory

| Path | Source capture | Recorded form | Integrity hint | Materialization path |
| --- | --- | --- | --- | --- |
| `readout_calibration_entrypoint.ipynb` | `content_captured` | `source_without_outputs` | `sha256`, 2840 bytes | `code/readout_calibration_entrypoint.ipynb` |
| `experiment_session_setup.ipynb` | `content_captured` | `source_without_outputs` | `sha256`, 1936 bytes | `code/experiment_session_setup.ipynb` |
| `helpers/record_measurement_context.py` | `content_captured` | `source_file` | `sha256`, 712 bytes | `code/helpers/record_measurement_context.py` |

The managed inventory depends on content-captured source entries. Reference-only
or redacted prior code records would remain comparison gaps unless a later
capture or observation supplies inventory facts.

## Attention

- `managed_storage_record_only`: final storage architecture is not decided.
- `integrity_hints_not_storage_contract`: checksums and sizes are not an archive or content-addressed store contract.
- `materialization_not_performed`: no editable workspace is created.
- `environment_not_restored`: no environment is synced or checked.
- `code_execution_not_granted`: code files are not loaded, imported, or executed.
- `internal_git_not_inspected`: Git state remains out of scope.

## Out Of Scope

This fixture does not accept final storage, archive, restore, sync,
environment, selected-version loading, code execution, merge, workflow/DAG, or
GUI behavior.
