from __future__ import annotations

from pathlib import Path

from demo_lab_readout_iq_testkit import create_readout_iq_run
from demo_lab_records import assert_artifact_ref
from scopecat.models.data_artifact import DataArraySchema, DataTableSchema
from scopecat.runs import (
    open_run_store,
    read_data_array_artifact,
    read_data_table_artifact,
)
from scopecat.workflows import read_run_data_array, read_run_data_table

from quantum_lab_demo.readout.iq_quality_processing import (
    READOUT_IQ_MATRIX_ARTIFACT_ID,
    READOUT_IQ_MATRIX_REF,
    READOUT_IQ_METRICS_ARTIFACT_ID,
    READOUT_IQ_METRICS_REF,
    execute_readout_iq_quality_processing,
)


def test_readout_iq_quality_persists_metrics_table_and_matrix_array(
    tmp_path: Path,
) -> None:
    run_id = create_readout_iq_run(tmp_path)
    _job, result = execute_readout_iq_quality_processing(
        run_id=run_id,
        workspace=tmp_path,
    )
    storage = open_run_store(tmp_path)
    updated_manifest = storage.read_manifest(run_id)

    metrics_artifact = assert_artifact_ref(
        updated_manifest.artifact_refs,
        READOUT_IQ_METRICS_ARTIFACT_ID,
        kind="data_table",
        path=READOUT_IQ_METRICS_REF,
    )
    assert metrics_artifact.metadata["data_shape"] == "table"
    assert metrics_artifact.metadata["source_step"] == "readout-iq-quality-processing"
    assert metrics_artifact.metadata["source_artifact_ids"] == ["raw-measurements"]
    metrics_schema = DataTableSchema.model_validate(
        metrics_artifact.metadata["data_schema"]
    )
    assert metrics_schema.schema_version == "scopecat.data_table_schema.v0"
    assert [column.id for column in metrics_schema.columns] == [
        "threshold",
        "p00",
        "p11",
        "visibility",
        "snr",
        "separation_error",
    ]
    metrics_payload = read_data_table_artifact(
        storage=storage,
        run_id=run_id,
        selector=READOUT_IQ_METRICS_ARTIFACT_ID,
    )
    workflow_metrics = read_run_data_table(
        run_id=run_id,
        selector=READOUT_IQ_METRICS_ARTIFACT_ID,
        workspace=tmp_path,
    )
    assert metrics_payload.schema_version == "scopecat.data_table.v0"
    assert workflow_metrics.artifact.id == READOUT_IQ_METRICS_ARTIFACT_ID
    assert workflow_metrics.table == metrics_payload
    assert metrics_payload.data_schema == metrics_schema
    assert metrics_payload.rows == [
        {
            "threshold": result.threshold.value,
            "p00": result.p00.value,
            "p11": result.p11.value,
            "visibility": result.visibility.value,
            "snr": result.snr.value,
            "separation_error": result.separation_error.value,
        }
    ]

    matrix_artifact = assert_artifact_ref(
        updated_manifest.artifact_refs,
        READOUT_IQ_MATRIX_ARTIFACT_ID,
        kind="data_array",
        path=READOUT_IQ_MATRIX_REF,
    )
    assert matrix_artifact.metadata["data_shape"] == "array"
    assert matrix_artifact.metadata["source_step"] == "readout-iq-quality-processing"
    assert matrix_artifact.metadata["source_artifact_ids"] == ["raw-measurements"]
    matrix_schema = DataArraySchema.model_validate(
        matrix_artifact.metadata["data_schema"]
    )
    assert matrix_schema.schema_version == "scopecat.data_array_schema.v0"
    assert [dimension.id for dimension in matrix_schema.dimensions] == [
        "prepared_state",
        "assigned_state",
    ]
    assert matrix_schema.variables[0].id == "readout_probability"
    assert matrix_schema.variables[0].dims == [
        "prepared_state",
        "assigned_state",
    ]
    assert matrix_schema.variables[0].shape == [2, 2]
    matrix_payload = read_data_array_artifact(
        storage=storage,
        run_id=run_id,
        selector=READOUT_IQ_MATRIX_ARTIFACT_ID,
    )
    workflow_matrix = read_run_data_array(
        run_id=run_id,
        selector=READOUT_IQ_MATRIX_ARTIFACT_ID,
        workspace=tmp_path,
    )
    assert matrix_payload.schema_version == "scopecat.data_array.v0"
    assert workflow_matrix.artifact.id == READOUT_IQ_MATRIX_ARTIFACT_ID
    assert workflow_matrix.array == matrix_payload
    assert matrix_payload.data_schema == matrix_schema
    assert matrix_payload.variables["readout_probability"] == [
        [result.readout_matrix[0][0], result.readout_matrix[1][0]],
        [result.readout_matrix[0][1], result.readout_matrix[1][1]],
    ]
