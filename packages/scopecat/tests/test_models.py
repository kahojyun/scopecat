from pathlib import Path

import pytest
from pydantic import ValidationError

from scopecat.models.config import (
    ConfigProfile,
    load_config_profile,
)
from scopecat.models.parameter import (
    ParameterCatalog,
    ParameterState,
    ParameterTableColumn,
    ParameterTableDefinition,
    ParameterValue,
    ParameterValueSet,
    Quantity,
)
from tests.support.records import assert_model_round_trip, read_model

EXAMPLE_DIR = Path(__file__).parents[3] / "fixtures" / "core" / "simple_scan"


def test_config_profile_round_trip() -> None:
    config = read_model(EXAMPLE_DIR / "config-profile.json", ConfigProfile)
    restored = assert_model_round_trip(
        config,
        schema_version="scopecat.config_profile.v0",
    )

    assert restored.system_ref == "system-spec.json"
    assert restored.environment_ref == "environment-spec.json"
    assert restored.parameter_state_ref == "parameter-state.json"


def test_config_profile_snapshot_round_trip() -> None:
    snapshot = load_config_profile(EXAMPLE_DIR / "config-profile.json")
    restored = assert_model_round_trip(
        snapshot,
        schema_version="scopecat.config_profile_snapshot.v0",
    )

    assert restored.source is not None
    assert restored.source.system_ref is not None
    assert restored.parameter_build is not None
    assert restored.parameter_build.schema_version == (
        "scopecat.parameter_build_snapshot.v1"
    )
    assert restored.parameter_catalog.schema_version == "scopecat.parameter_catalog.v1"
    assert restored.parameter_build is not None
    assert restored.parameter_build.get("drive_frequency") is not None
    connection = restored.connection_profile.connections[0]
    assert connection.kind == "offline"
    assert "redacted" not in connection.model_dump(mode="json")


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
                primary_key=["point_id"],
                columns=[
                    ParameterTableColumn(id="point_id", kind="string"),
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
