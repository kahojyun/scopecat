from __future__ import annotations

import pytest
from pydantic import ValidationError

from scopecat.importers import (
    ImportedParameterTable,
    ImportSourceLocation,
    import_diagnostic,
    parameter_import_result,
)


def test_parameter_import_result_tracks_blocking_diagnostics() -> None:
    result = parameter_import_result(
        id="blocked-import",
        source_kind="legacy",
        source_uri="legacy://calibration",
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

    assert result.has_errors is True
    assert result.parameter_state.metadata["import_source_kind"] == "legacy"
    assert result.diagnostics[0].location is not None


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
