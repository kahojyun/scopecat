# Managed Code Version Review

## Fixture

- Source: `managed-code-version-input.json`
- Boundary: managed code-version record candidate
- Status: fixture output, not product contract

## Managed Version

- Version: `managed-code-version-readout-0001`
- Source candidate: `code-version-candidate-0001`
- Stable ID: `sc-codever-readout-0001`
- Storage authority: `scopecat_managed_candidate_record`
- Files: 3
- Notebook files: 2

## File Inventory

| Path | Recorded form | Integrity hint | Materialization path |
| --- | --- | --- | --- |
| `readout_calibration_entrypoint.ipynb` | `source_without_outputs` | `sha256`, 2840 bytes | `code/readout_calibration_entrypoint.ipynb` |
| `experiment_session_setup.ipynb` | `source_without_outputs` | `sha256`, 1936 bytes | `code/experiment_session_setup.ipynb` |
| `helpers/record_measurement_context.py` | `source_file` | `sha256`, 712 bytes | `code/helpers/record_measurement_context.py` |

## Attention

- `managed_storage_candidate_only`: final storage architecture is not decided.
- `integrity_hints_not_storage_contract`: checksums and sizes are not an archive or content-addressed store contract.
- `materialization_not_performed`: no editable workspace is created.
- `environment_not_restored`: no environment is synced or checked.
- `code_execution_not_granted`: recorded code is not loaded, imported, or executed.
- `internal_git_not_inspected`: Git state remains out of scope.

## Out Of Scope

This fixture does not accept final storage, archive, restore, sync,
environment, selected-version loading, code execution, merge, workflow/DAG, or
GUI behavior.
