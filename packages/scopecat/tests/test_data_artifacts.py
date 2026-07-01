from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from scopecat._steps import StepArtifactStore
from scopecat._storage import ARTIFACTS_DIR
from scopecat.errors import ValidationFailed
from scopecat.models.data_artifact import (
    DataArrayArtifact,
    DataArrayDimension,
    DataArraySchema,
    DataArrayVariable,
    DataTableArtifact,
    DataTableSchema,
)
from tests.support.data_artifacts import (
    artifact_diagnostics,
    metrics_table_schema,
    readout_matrix_schema,
)
from tests.support.records import read_model


def test_data_table_artifact_rejects_invalid_row() -> None:
    schema = metrics_table_schema()

    with pytest.raises(ValidationError):
        DataTableArtifact(
            schema=schema,
            rows=[{"metric": "visibility", "value": 0.98}],
        )


def test_data_array_artifact_rejects_invalid_schema_refs() -> None:
    with pytest.raises(ValidationError):
        DataArraySchema(
            dimensions=[
                DataArrayDimension(id="prepared_state", kind="state", size=2),
            ],
            variables=[
                DataArrayVariable(
                    id="readout_probability",
                    role="observable",
                    dtype="float64",
                    unit="ratio",
                    dims=["missing"],
                    shape=[2],
                )
            ],
        )


def test_step_artifact_store_writes_typed_data_artifacts(tmp_path: Path) -> None:
    store = StepArtifactStore(
        root_dir=tmp_path,
        ref_dir=ARTIFACTS_DIR,
        diagnostics=artifact_diagnostics(),
    )
    table_schema = metrics_table_schema()
    array_schema = readout_matrix_schema()

    table = store.write_data_table(
        id="metrics",
        filename="metrics.json",
        schema=table_schema,
        rows=[{"metric": "visibility", "value": 0.98, "passed": True}],
        source_step="quality",
        source_artifact_ids=["raw-measurements"],
        metadata={"category": "readout"},
    )
    array = store.write_data_array(
        id="readout-matrix",
        filename="readout-matrix.json",
        schema=array_schema,
        variables={"readout_probability": [[0.99, 0.03], [0.01, 0.97]]},
        source_step="quality",
        source_artifact_ids=["raw-measurements"],
    )

    assert store.output_artifact_ids == ("metrics", "readout-matrix")
    artifacts = {artifact.id: artifact for artifact in store.artifacts}
    assert table.kind == "data_table"
    assert artifacts["metrics"].kind == "data_table"
    assert artifacts["metrics"].media_type == "application/json"
    assert artifacts["metrics"].metadata["category"] == "readout"
    assert artifacts["metrics"].metadata["data_shape"] == "table"
    assert (
        DataTableSchema.model_validate(artifacts["metrics"].metadata["data_schema"])
        == table_schema
    )
    assert artifacts["metrics"].metadata["source_step"] == "quality"
    assert artifacts["metrics"].metadata["source_artifact_ids"] == ["raw-measurements"]

    assert array.kind == "data_array"
    assert artifacts["readout-matrix"].kind == "data_array"
    assert artifacts["readout-matrix"].metadata["data_shape"] == "array"
    assert (
        DataArraySchema.model_validate(
            artifacts["readout-matrix"].metadata["data_schema"]
        )
        == array_schema
    )

    table_payload = read_model(table.path, DataTableArtifact)
    assert table_payload.schema_version == "scopecat.data_table.v0"
    assert table_payload.data_schema == table_schema
    assert table_payload.rows == [
        {"metric": "visibility", "value": 0.98, "passed": True}
    ]

    array_payload = read_model(array.path, DataArrayArtifact)
    assert array_payload.schema_version == "scopecat.data_array.v0"
    assert array_payload.data_schema == array_schema
    assert array_payload.variables == {
        "readout_probability": [[0.99, 0.03], [0.01, 0.97]]
    }


def test_step_artifact_store_rejects_invalid_typed_data_payload(
    tmp_path: Path,
) -> None:
    store = StepArtifactStore(
        root_dir=tmp_path,
        ref_dir=ARTIFACTS_DIR,
        diagnostics=artifact_diagnostics(),
    )

    with pytest.raises(ValidationFailed) as table_error:
        store.write_data_table(
            id="metrics",
            filename="metrics.json",
            schema=metrics_table_schema(),
            rows=[{"metric": "visibility", "value": 0.98}],
        )
    with pytest.raises(ValidationFailed) as array_error:
        store.write_data_array(
            id="readout-matrix",
            filename="readout-matrix.json",
            schema=readout_matrix_schema(),
            variables={"readout_probability": [[0.99, 0.03]]},
        )

    assert table_error.value.diagnostics[0].code == "invalid_data_table_artifact"
    assert array_error.value.diagnostics[0].code == "invalid_data_array_artifact"
