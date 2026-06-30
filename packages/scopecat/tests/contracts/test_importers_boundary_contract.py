from __future__ import annotations

import pytest
from pydantic import ValidationError

import scopecat as sc
from scopecat.importers import (
    ImportedParameterTable,
    ImportedScalarParameter,
    ImportSourceLocation,
    import_diagnostic,
    parameter_import_result,
)
from scopecat.models.artifact import Artifact
from scopecat.models.parameter import Quantity
from tests.support.records import assert_model_round_trip


def test_parameter_import_result_emits_typed_state_and_source_diagnostics() -> None:
    scalar_location = ImportSourceLocation(
        source_uri="file://calibration.csv",
        row=2,
        column="drive_frequency",
    )
    table_location = ImportSourceLocation(
        source_uri="file://calibration.xlsx",
        sheet="readout",
        path="tables.readout_devices",
    )
    row_location = ImportSourceLocation(
        source_uri="file://calibration.xlsx",
        sheet="readout",
        row=3,
    )
    result = parameter_import_result(
        id="public-import",
        source_kind="csv",
        source_uri="file://calibration.csv",
        scalars=[
            ImportedScalarParameter(
                id="drive_frequency",
                quantity=Quantity(value=5.0, unit="GHz"),
                location=scalar_location,
            )
        ],
        tables=[
            ImportedParameterTable(
                id="readout_devices",
                rows=[{"device_id": "r0", "enabled": True}],
                location=table_location,
                row_locations=[row_location],
            )
        ],
        artifact_refs=[
            Artifact(
                id="public-import-parameter-state",
                kind="parameter_state",
                path="imports/public-import.parameter-state.json",
                media_type="application/json",
                metadata={"source_uri": "file://calibration.csv"},
            )
        ],
        diagnostics=[
            import_diagnostic(
                severity="warning",
                code="import_column_unit_inferred",
                message="column unit was inferred from the header",
                location=scalar_location,
            )
        ],
    )

    assert_model_round_trip(
        result,
        schema_version="scopecat.parameter_import_result.v1",
    )
    assert [
        (artifact.id, artifact.kind, artifact.path) for artifact in result.artifact_refs
    ] == [
        (
            "public-import-parameter-state",
            "parameter_state",
            "imports/public-import.parameter-state.json",
        )
    ]
    assert result.parameter_state.schema_version == "scopecat.parameter_state.v1"
    assert result.parameter_state.scalar_value_set().get("drive_frequency") is not None
    assert result.parameter_state.metadata == {
        "import_source_kind": "csv",
        "import_source_uri": "file://calibration.csv",
    }
    assert result.parameter_state.scalar_values.values[0].metadata[
        "import_location"
    ] == {
        "source_uri": "file://calibration.csv",
        "row": 2,
        "column": "drive_frequency",
    }
    assert result.parameter_state.tables[0].metadata["import_row_locations"] == [
        {
            "source_uri": "file://calibration.xlsx",
            "sheet": "readout",
            "row": 3,
        }
    ]
    assert result.diagnostics[0].location == scalar_location
    assert result.has_errors is False
    assert not hasattr(sc, "parameter_import_result")


def test_parameter_import_result_reports_blocking_diagnostics() -> None:
    result = parameter_import_result(
        id="blocked-import",
        source_kind="legacy",
        source_uri="legacy://calibration",
        artifact_refs=[
            Artifact(
                id="blocked-import-diagnostics",
                kind="import_diagnostics",
                path="imports/blocked-import.diagnostics.json",
                media_type="application/json",
            )
        ],
        diagnostics=[
            import_diagnostic(
                severity="error",
                code="import_required_value_missing",
                message="drive frequency was missing",
                location=ImportSourceLocation(
                    source_uri="legacy://calibration",
                    path="parameters.drive_frequency",
                ),
            )
        ],
    )

    restored = assert_model_round_trip(result)

    assert restored == result
    assert restored.artifact_refs[0].kind == "import_diagnostics"
    assert restored.has_errors is True
    assert restored.diagnostics[0].location is not None
    assert restored.diagnostics[0].location.path == "parameters.drive_frequency"


def test_imported_parameter_table_requires_row_location_cardinality() -> None:
    with pytest.raises(ValidationError):
        ImportedParameterTable(
            id="readout_devices",
            rows=[{"device_id": "r0"}, {"device_id": "r1"}],
            location=ImportSourceLocation(source_uri="file://calibration.csv"),
            row_locations=[
                ImportSourceLocation(source_uri="file://calibration.csv", row=2)
            ],
        )
