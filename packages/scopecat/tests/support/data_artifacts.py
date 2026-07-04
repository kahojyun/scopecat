from __future__ import annotations

from scopecat._steps import StepArtifactDiagnostics
from scopecat.models.data_artifact import (
    DataArrayDimension,
    DataArraySchema,
    DataArrayVariable,
    DataColumn,
    DataTableSchema,
)


def metrics_table_schema() -> DataTableSchema:
    return DataTableSchema(
        columns=[
            DataColumn(id="metric", role="identifier", dtype="string"),
            DataColumn(id="value", role="observable", dtype="float64", unit="ratio"),
            DataColumn(id="passed", role="status", dtype="bool"),
        ],
        primary_key=["metric"],
    )


def readout_matrix_schema() -> DataArraySchema:
    return DataArraySchema(
        dimensions=[
            DataArrayDimension(
                id="prepared_state",
                kind="state",
                size=2,
                metadata={"labels": ["0", "1"]},
            ),
            DataArrayDimension(
                id="assigned_state",
                kind="state",
                size=2,
                metadata={"labels": ["0", "1"]},
            ),
        ],
        variables=[
            DataArrayVariable(
                id="readout_probability",
                role="observable",
                dtype="float64",
                unit="ratio",
                dims=["prepared_state", "assigned_state"],
                shape=[2, 2],
            )
        ],
        primary_variables=["readout_probability"],
    )


def artifact_diagnostics() -> StepArtifactDiagnostics:
    return StepArtifactDiagnostics(
        missing_id_code="test_missing_artifact",
        duplicate_id_code="test_duplicate_artifact",
        missing_kind_code="test_missing_kind",
        noun="test artifact",
        path_prefix="artifacts",
    )
