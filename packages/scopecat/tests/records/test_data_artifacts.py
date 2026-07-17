from __future__ import annotations

import pytest
from pydantic import ValidationError

from scopecat.records.data_artifact import (
    DataArrayDimension,
    DataArraySchema,
    DataArrayVariable,
    DataTableArtifact,
)
from tests.testkit.data_artifacts import metrics_table_schema


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
