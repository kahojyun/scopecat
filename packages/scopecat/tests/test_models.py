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
from scopecat.value_types import Bool, Float, Int, Payload, Scalar, String
from scopecat.value_types import Quantity as QuantityType
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
    assert restored.parameter_catalog.schema_version == "scopecat.parameter_catalog.v2"
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
        schema_version="scopecat.run_request.v2",
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
        schema_version="scopecat.run_request.v2",
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
                "schema_version": "scopecat.run_request.v1",
                "id": "request-002",
            }
        )
    with pytest.raises(ValidationError):
        RunRequest.model_validate(
            {
                "id": "request-002",
                "scans": [
                    {
                        "kind": "point",
                        "target_id": "drive_frequency",
                        "axis_id": "drive_frequency",
                        "values": [5.0],
                        "input_id": "frequencies",
                    }
                ],
            }
        )
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
                    ParameterTableColumn(
                        id="point_index",
                        value_type=Scalar(String()),
                    ),
                    ParameterTableColumn(
                        id="frequency",
                        value_type=Scalar(QuantityType(unit="GHz")),
                    ),
                ],
            )
        ],
    )

    restored = assert_model_round_trip(catalog)

    assert restored.table("calibration_points") is not None


@pytest.mark.parametrize(
    "value_type",
    [
        Scalar(Bool()),
        Scalar(Int(minimum=1, maximum=3)),
        Scalar(Float(minimum=0.0, maximum=1.0)),
        Scalar(String(min_length=1, choices=("a", "b"))),
        Scalar(
            QuantityType(
                dimension="frequency",
                unit="GHz",
                minimum=4.0,
                maximum=6.0,
            ),
            nullable=True,
        ),
    ],
)
def test_parameter_table_column_scalar_type_has_stable_wire_format(
    value_type: Scalar,
) -> None:
    column = ParameterTableColumn(id="value", value_type=value_type)

    compact = column.model_dump(mode="json", exclude_defaults=True)
    restored = ParameterTableColumn.model_validate(compact)
    restored_from_json = ParameterTableColumn.model_validate_json(
        column.model_dump_json()
    )

    assert compact["value_type"]["type"]
    assert restored == column
    assert restored_from_json == column
    assert restored_from_json.model_dump_json() == column.model_dump_json()
    assert not hasattr(column, "kind")


def test_parameter_table_column_wire_is_strict_and_schema_matches_it() -> None:
    column = ParameterTableColumn(
        id="value",
        value_type=Scalar(Float(minimum=0)),
    )
    value_type = column.value_type

    assert isinstance(value_type.atom, Float)
    assert value_type.atom.minimum == 0.0
    with pytest.raises(ValidationError, match="unknown fields: garbage"):
        ParameterTableColumn.model_validate(
            {
                "id": "value",
                "value_type": {"type": "bool", "garbage": True},
            }
        )
    with pytest.raises(ValidationError, match="must require finite values"):
        ParameterTableColumn(
            id="value",
            value_type=Scalar(Float(finite=False)),
        )
    with pytest.raises(ValidationError, match="support bool, int, float, string"):
        ParameterTableColumn(
            id="value",
            value_type=Scalar(Payload("pulse_program")),
        )
    with pytest.raises(ValidationError, match="field 'finite' must be a bool"):
        ParameterTableColumn.model_validate(
            {
                "id": "value",
                "value_type": {"type": "float", "finite": "false"},
            }
        )
    with pytest.raises(ValidationError, match="field names must be strings"):
        ParameterTableColumn.model_validate(
            {
                "id": "value",
                "value_type": {"type": "float", 1: "unexpected"},
            }
        )

    integer_column = ParameterTableColumn.model_validate(
        {
            "id": "value",
            "value_type": {"type": "int", "minimum": 1.0},
        }
    )
    assert isinstance(integer_column.value_type.atom, Int)
    assert integer_column.value_type.atom.minimum == 1

    schema = ParameterTableColumn.model_json_schema(mode="validation")
    value_schema = schema["properties"]["value_type"]
    definition_name = value_schema["$ref"].rsplit("/", maxsplit=1)[-1]
    wire_schema = schema["$defs"][definition_name]
    assert len(wire_schema["oneOf"]) == 5
    assert all(
        variant["additionalProperties"] is False for variant in wire_schema["oneOf"]
    )


def test_durable_scalar_models_reject_malformed_runtime_declarations() -> None:
    invalid_nullable = Scalar(Float())
    object.__setattr__(invalid_nullable, "nullable", "false")
    invalid_finite = Float()
    object.__setattr__(invalid_finite, "finite", "false")
    invalid_length = String()
    object.__setattr__(invalid_length, "min_length", False)

    for value_type in (
        invalid_nullable,
        Scalar(invalid_finite),
        Scalar(invalid_length),
    ):
        with pytest.raises(ValidationError):
            ParameterTableColumn(id="value", value_type=value_type)


@pytest.mark.parametrize(
    "column",
    [
        ParameterTableColumn(
            id="id",
            value_type=Scalar(String()),
            required=False,
        ),
        ParameterTableColumn(
            id="id",
            value_type=Scalar(String(), nullable=True),
        ),
    ],
)
def test_parameter_table_primary_key_must_be_required_and_non_null(
    column: ParameterTableColumn,
) -> None:
    with pytest.raises(ValidationError, match="required and non-null"):
        ParameterTableDefinition(
            id="values",
            primary_key=["id"],
            columns=[column],
        )
