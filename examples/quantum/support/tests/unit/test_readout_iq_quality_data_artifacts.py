from __future__ import annotations

from pathlib import Path

from demo_lab_readout_iq_testkit import create_readout_iq_run
from demo_lab_records import assert_artifact_ref
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
    execute_readout_iq_quality_processing(
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

    assert workflow_metrics.artifact.id == READOUT_IQ_METRICS_ARTIFACT_ID
    assert workflow_metrics.table == metrics_payload
    assert len(metrics_payload.rows) == 1
    assert {"threshold", "visibility", "snr"} <= set(metrics_payload.rows[0])

    matrix_artifact = assert_artifact_ref(
        updated_manifest.artifact_refs,
        READOUT_IQ_MATRIX_ARTIFACT_ID,
        kind="data_array",
        path=READOUT_IQ_MATRIX_REF,
    )
    assert matrix_artifact.metadata["data_shape"] == "array"
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
    assert workflow_matrix.artifact.id == READOUT_IQ_MATRIX_ARTIFACT_ID
    assert workflow_matrix.array == matrix_payload
    readout_probability = matrix_payload.variables["readout_probability"]
    assert len(readout_probability) == 2
    assert all(len(row) == 2 for row in readout_probability)
