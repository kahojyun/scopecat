from pathlib import Path

import pytest
from pydantic import ValidationError

from scopecat.config_profiles import load_config_profile
from scopecat.experiments import PointScanRecord, RunRequest
from scopecat.models.config import build_config_parameters
from scopecat.models.parameter import (
    ParameterCatalog,
    ParameterState,
    ParameterTableColumn,
    ParameterTableDefinition,
    ParameterValue,
    ParameterValueSet,
    Quantity,
)
from tests.support.records import assert_model_round_trip

EXAMPLE_DIR = Path(__file__).parents[3] / "fixtures" / "core" / "simple_scan"


def test_config_profile_snapshot_round_trip() -> None:
    snapshot = load_config_profile(EXAMPLE_DIR / "config-profile.json")
    restored = assert_model_round_trip(
        snapshot,
        schema_version="scopecat.config_profile_snapshot.v0",
    )

    assert "source" not in restored.model_dump(mode="python")
    assert "parameter_view" not in restored.model_dump(mode="python")
    parameter_view = build_config_parameters(restored)
    assert parameter_view.schema_version == ("scopecat.parameter_view_snapshot.v1")
    assert restored.parameter_catalog.schema_version == "scopecat.parameter_catalog.v1"
    assert parameter_view.get("drive_frequency") is not None
    assert restored.topology.entity("q0") is not None
    connection = restored.connection_profile.connections[0]
    assert connection.kind == "offline"
    assert "redacted" not in connection.model_dump(mode="json")


def test_run_request_records_config_source() -> None:
    request = RunRequest(
        id="request-001",
        template_id="test.template",
        config_source="active",
    )
    restored = assert_model_round_trip(
        request,
        schema_version="scopecat.run_request.v1",
    )

    assert restored.config_source == "active"


def test_run_request_records_canonical_scans_only() -> None:
    request = RunRequest(
        id="request-001",
        scans=[
            PointScanRecord(
                target_id="drive_frequency",
                axis_id="drive_frequency",
                values=[5.0, 5.1],
                unit="GHz",
            )
        ],
    )
    restored = assert_model_round_trip(
        request,
        schema_version="scopecat.run_request.v1",
    )

    assert restored.scans == request.scans
    assert isinstance(restored.scans[0], PointScanRecord)
    assert restored.model_dump(mode="json")["scans"] == [
        {
            "kind": "point",
            "target_id": "drive_frequency",
            "axis_id": "drive_frequency",
            "values": [5.0, 5.1],
            "unit": "GHz",
        }
    ]
    with pytest.raises(ValidationError):
        RunRequest.model_validate(
            {
                "id": "request-003",
                "scans": [
                    {
                        "kind": "point",
                        "target_id": "drive_frequency",
                        "axis_id": "drive_frequency",
                        "unit": "GHz",
                    }
                ],
            }
        )
    with pytest.raises(ValidationError):
        RunRequest.model_validate(
            {
                "id": "request-004",
                "scans": [
                    {
                        "kind": "unknown",
                        "axis_id": "drive_frequency",
                    }
                ],
            }
        )


def test_parameter_state_requires_scalar_values() -> None:
    with pytest.raises(ValidationError):
        ParameterState(
            id="missing-scalars",
            scalar_values=None,  # type: ignore[arg-type]
        )


def test_parameter_state_uses_scalar_values() -> None:
    state = ParameterState(
        id="parameter-state",
        scalar_values=ParameterValueSet(
            id="parameter-values",
            values=[
                ParameterValue(
                    id="drive_frequency",
                    quantity=Quantity(value=5.0, unit="GHz"),
                )
            ],
        ),
    )

    assert state.scalar_value_set().get("drive_frequency") is not None


def test_parameter_state_rejects_embedded_derivations() -> None:
    with pytest.raises(ValidationError):
        ParameterState.model_validate(
            {
                "id": "parameter-state",
                "scalar_values": {"id": "values", "values": []},
                "derivations": {"id": "derivations"},
            }
        )


def test_parameter_catalog_supports_table_definitions() -> None:
    catalog = ParameterCatalog(
        id="public-lab-catalog",
        table_definitions=[
            ParameterTableDefinition(
                id="calibration_points",
                primary_key=["point_index"],
                columns=[
                    ParameterTableColumn(id="point_index", kind="string"),
                    ParameterTableColumn(
                        id="frequency",
                        kind="quantity",
                        unit="GHz",
                    ),
                ],
            )
        ],
    )

    restored = assert_model_round_trip(catalog)

    assert restored.table("calibration_points") is not None
