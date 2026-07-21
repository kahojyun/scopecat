from collections.abc import Callable
from dataclasses import dataclass

import pytest
from pydantic import BaseModel, ValidationError

from scopecat.config.profiles import load_config_profile
from scopecat.kernel.value_types import (
    Bool,
    Entity,
    Float,
    Int,
    Payload,
    Scalar,
    Series,
    String,
    Table,
    TableColumn,
)
from scopecat.kernel.value_types import Quantity as QuantityType
from scopecat.records.artifact import RunContentEntry
from scopecat.records.config import TopologyLine
from scopecat.records.entity import EntityRef
from scopecat.records.parameter import (
    ParameterCatalog,
    ParameterDefinition,
    ParameterSnapshot,
    Quantity,
    ScalarParameterValue,
    SeriesParameterValue,
    TableParameterValue,
)
from scopecat.records.run_request import (
    AroundScanRecord,
    PointScanRecord,
    RunRequest,
    RunRequestEntityRef,
    RunRequestParameterValue,
)
from tests.testkit.paths import CORE_FIXTURE_DIR as EXAMPLE_DIR
from tests.testkit.records import assert_model_round_trip

type _MetadataModelFactory = Callable[[object], BaseModel]


def _topology_line_with_metadata(value: object) -> TopologyLine:
    return TopologyLine.model_validate(
        {"id": "line", "kind": "signal", "metadata": {"value": value}}
    )


def _artifact_with_metadata(value: object) -> RunContentEntry:
    return RunContentEntry.model_validate(
        {"id": "artifact", "kind": "attachment", "metadata": {"value": value}}
    )


_METADATA_MODEL_FACTORIES: tuple[_MetadataModelFactory, ...] = (
    _topology_line_with_metadata,
    _artifact_with_metadata,
)


@pytest.mark.parametrize("value", [(1, 2), object(), float("nan")])
@pytest.mark.parametrize(
    "model",
    _METADATA_MODEL_FACTORIES,
)
def test_durable_metadata_boundaries_reject_non_json_values(
    model: _MetadataModelFactory,
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        model(value)


def test_config_profile_snapshot_round_trip() -> None:
    snapshot = load_config_profile(EXAMPLE_DIR / "config-profile.json")
    restored = assert_model_round_trip(
        snapshot,
        schema_version="scopecat.config_profile_snapshot.v2",
    )

    assert "source" not in restored.model_dump(mode="python")
    assert restored.parameter_catalog.schema_version == "scopecat.parameter_catalog.v4"
    assert restored.parameter_snapshot.get("drive_frequency") is not None
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
        schema_version="scopecat.run_request.v4",
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
        schema_version="scopecat.run_request.v4",
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
                "schema_version": "scopecat.run_request.v3",
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


def test_run_request_values_have_a_closed_durable_domain() -> None:
    request = RunRequest.model_validate(
        {
            "id": "request-001",
            "template_inputs": {
                "subject": {
                    "kind": "entity",
                    "entity_id": "q0",
                    "entity_kind": "qubit",
                    "metadata": {},
                },
                "frequency": Quantity(value=5.0, unit="GHz"),
                "settings": {"enabled": True, "labels": ["a", "b"]},
            },
            "scans": [
                {
                    "kind": "scan",
                    "target_id": "drive_frequency",
                    "axis_id": "drive_frequency",
                    "center": {
                        "kind": "parameter",
                        "parameter_id": "drive_frequency",
                    },
                    "span": Quantity(value=100.0, unit="MHz"),
                    "points": 3,
                },
            ],
            "segment_lineage": {"parent_ids": ["run-001"]},
            "metadata": {"notebook": "02_define_experiment"},
        }
    )

    assert isinstance(request.template_inputs["subject"], RunRequestEntityRef)
    assert request.template_inputs["subject"] == RunRequestEntityRef(
        entity_id="q0",
        entity_kind="qubit",
    )
    assert request.model_dump(mode="json")["template_inputs"]["subject"] == {
        "kind": "entity",
        "entity_id": "q0",
        "entity_kind": "qubit",
        "metadata": {},
    }
    assert isinstance(request.template_inputs["frequency"], Quantity)
    scan = request.scans[0]
    assert isinstance(scan, AroundScanRecord)
    assert scan.center == RunRequestParameterValue(parameter_id="drive_frequency")
    assert scan.span == Quantity(value=100.0, unit="MHz")
    assert RunRequest.model_validate_json(request.model_dump_json()) == request


def test_run_request_does_not_guess_entities_from_business_mappings() -> None:
    request = RunRequest.model_validate(
        {
            "id": "request-001",
            "template_inputs": {"settings": {"id": "business-object"}},
        }
    )

    assert request.template_inputs["settings"] == {"id": "business-object"}
    assert request.model_dump(mode="json")["template_inputs"]["settings"] == {
        "id": "business-object"
    }


def test_run_request_does_not_duck_project_semantic_python_objects() -> None:
    class SemanticModel(BaseModel):
        value: str

    @dataclass(frozen=True)
    class SemanticDataclass:
        value: str

    values = (
        EntityRef(id="q0", kind="qubit"),
        SemanticModel(value="model"),
        SemanticDataclass(value="dataclass"),
    )

    for value in values:
        with pytest.raises(
            ValidationError,
            match="unsupported durable run request value",
        ):
            RunRequest.model_validate(
                {
                    "id": "request-001",
                    "template_inputs": {"value": value},
                }
            )


def test_run_request_symbolic_values_are_closed_and_recursive() -> None:
    center = {
        "kind": "binary",
        "operator": "+",
        "left": {"kind": "input", "input_id": "frequency_offset"},
        "right": {
            "kind": "parameter_lookup",
            "table_id": "device_parameters",
            "key": {
                "subject": {"kind": "axis", "axis_id": "subject"},
            },
            "column": "frequency",
        },
    }
    scan = AroundScanRecord.model_validate(
        {
            "target_id": "drive_frequency",
            "axis_id": "drive_frequency",
            "center": center,
            "span": Quantity(value=100.0, unit="MHz"),
            "points": 3,
        }
    )

    assert scan.model_dump(mode="json")["center"] == center
    assert AroundScanRecord.model_validate_json(scan.model_dump_json()) == scan


def test_run_request_rejects_removed_case_expression_schema() -> None:
    with pytest.raises(ValidationError):
        AroundScanRecord.model_validate(
            {
                "target_id": "drive_frequency",
                "axis_id": "drive_frequency",
                "center": {
                    "kind": "case",
                    "branches": [{"when": True, "then": 1.0}],
                    "fallback": 0.0,
                },
                "span": Quantity(value=100.0, unit="MHz"),
                "points": 3,
            }
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("template_inputs", {"opaque": object()}),
        ("metadata", {"opaque": object()}),
        ("segment_lineage", {"opaque": object()}),
    ],
)
def test_run_request_rejects_opaque_values_early(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError, match=r"unsupported .*run request"):
        RunRequest.model_validate({"id": "request-001", field: value})


def test_scan_records_reject_unknown_or_structured_scalar_values() -> None:
    with pytest.raises(ValidationError):
        AroundScanRecord.model_validate(
            {
                "target_id": "drive_frequency",
                "axis_id": "drive_frequency",
                "center": {"kind": "unknown", "value": 5.0},
                "span": 1.0,
                "points": 3,
            }
        )
    with pytest.raises(ValidationError):
        PointScanRecord.model_validate(
            {
                "target_id": "drive_frequency",
                "axis_id": "drive_frequency",
                "values": [{"arbitrary": "mapping"}],
            }
        )


def test_entity_metadata_is_closed_finite_json_at_capture() -> None:
    entity = EntityRef(
        id="q0",
        metadata={"labels": ("data", "ancilla"), "score": 0.5},
    )

    assert entity.metadata == {
        "labels": ("data", "ancilla"),
        "score": 0.5,
    }
    assert EntityRef.model_validate_json(entity.model_dump_json()) == entity
    with pytest.raises(ValidationError, match="durable JSON"):
        EntityRef(id="q0", metadata={"value": object()})
    with pytest.raises(ValidationError, match="finite"):
        EntityRef(id="q0", metadata={"value": float("nan")})


def test_table_parameter_cells_are_closed_finite_and_round_trip_without_catalog() -> (
    None
):
    table = TableParameterValue.model_validate(
        {
            "id": "typed-values",
            "shape": "table",
            "rows": [
                {
                    "enabled": True,
                    "count": 2,
                    "gain": 0.5,
                    "label": "q0",
                    "optional": None,
                    "frequency": {"value": 5.0, "unit": "GHz"},
                    "subject": {
                        "id": "q0",
                        "kind": "logical_qubit",
                        "metadata": {"labels": ["data"]},
                    },
                }
            ],
        }
    )

    subject = table.rows[0]["subject"]
    assert isinstance(subject, EntityRef)
    assert subject.metadata == {"labels": ("data",)}
    assert TableParameterValue.model_validate_json(table.model_dump_json()) == table

    with pytest.raises(ValidationError):
        TableParameterValue(
            id="invalid",
            rows=[{"value": object()}],  # pyright: ignore[reportArgumentType]
        )
    with pytest.raises(ValidationError, match="finite"):
        TableParameterValue(id="invalid", rows=[{"value": float("nan")}])
    with pytest.raises(ValidationError, match="finite"):
        TableParameterValue(
            id="invalid",
            rows=[{"value": Quantity(value=float("inf"), unit="GHz")}],
        )
    for value in (b"abc", bytearray(b"abc")):
        with pytest.raises(ValidationError):
            TableParameterValue(
                id="invalid",
                rows=[{"value": value}],  # pyright: ignore[reportArgumentType]
            )


def test_parameter_snapshot_is_recursively_immutable_and_durable() -> None:
    table = TableParameterValue(
        id="durable",
        rows=[{"value": 1.0}],
        metadata={"labels": ["data"]},
    )

    assert table.rows == ({"value": 1.0},)
    assert table.metadata == {"labels": ("data",)}
    with pytest.raises(ValidationError):
        TableParameterValue(id="invalid", metadata={"value": object()})
    with pytest.raises(ValidationError):
        TableParameterValue(id="invalid", metadata={"value": float("nan")})

    snapshot = ParameterSnapshot(id="snapshot", values=[table])
    assert ParameterSnapshot.model_validate_json(snapshot.model_dump_json()) == snapshot


def test_parameter_snapshot_uses_one_shape_discriminated_namespace() -> None:
    snapshot = ParameterSnapshot(
        id="parameter-snapshot",
        values=[
            ScalarParameterValue(id="enabled", value=True),
            SeriesParameterValue(id="frequencies", items=[4.9, 5.0]),
            TableParameterValue(id="calibrations", rows=[{"id": "q0"}]),
        ],
    )

    restored = ParameterSnapshot.model_validate_json(snapshot.model_dump_json())

    assert isinstance(restored.get("enabled"), ScalarParameterValue)
    assert isinstance(restored.get("frequencies"), SeriesParameterValue)
    assert isinstance(restored.get("calibrations"), TableParameterValue)
    with pytest.raises(ValidationError, match="duplicate stored parameter value"):
        ParameterSnapshot(
            id="duplicate",
            values=[
                ScalarParameterValue(id="same", value=1),
                SeriesParameterValue(id="same", items=[1]),
            ],
        )


def test_parameter_catalog_supports_all_value_shapes() -> None:
    catalog = ParameterCatalog(
        id="public-lab-catalog",
        definitions=[
            ParameterDefinition(
                id="enabled",
                value_type=Scalar(Bool()),
            ),
            ParameterDefinition(
                id="frequencies",
                value_type=Series(Scalar(QuantityType(unit="GHz"))),
            ),
            ParameterDefinition(
                id="calibration_points",
                value_type=Table(
                    primary_key=("point_index",),
                    columns=(
                        TableColumn(
                            id="point_index",
                            value_type=Scalar(String()),
                        ),
                        TableColumn(
                            id="frequency",
                            value_type=Scalar(QuantityType(unit="GHz")),
                        ),
                    ),
                ),
            ),
        ],
    )

    restored = assert_model_round_trip(catalog)

    enabled = restored.get("enabled")
    frequencies = restored.get("frequencies")
    calibration_points = restored.get("calibration_points")
    assert enabled is not None
    assert frequencies is not None
    assert calibration_points is not None
    assert isinstance(enabled.value_type, Scalar)
    assert isinstance(frequencies.value_type, Series)
    assert isinstance(calibration_points.value_type, Table)


def test_durable_parameter_schema_rejects_invalid_values() -> None:
    definition = ParameterDefinition(id="enabled", value_type=Scalar(Bool()))

    with pytest.raises(ValidationError, match="supports only bool, int, float"):
        ParameterDefinition(
            id="enabled",
            value_type=Scalar(Payload("command")),
        )
    with pytest.raises(ValidationError, match="duplicate parameter definition"):
        ParameterCatalog(id="catalog", definitions=[definition, definition])
    with pytest.raises(ValidationError, match="unsupported unit"):
        Quantity(1.0, "invalid")


@pytest.mark.parametrize(
    "value_type",
    [
        Scalar(Bool()),
        Scalar(Int(minimum=1, maximum=3)),
        Scalar(Float(minimum=0.0, maximum=1.0)),
        Scalar(String(min_length=1, choices=("a", "b"))),
        Scalar(Entity(entity_kind="qubit")),
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
def test_parameter_definition_scalar_type_has_stable_wire_format(
    value_type: Scalar,
) -> None:
    definition = ParameterDefinition(id="value", value_type=value_type)

    compact = definition.model_dump(mode="json", exclude_defaults=True)
    restored = ParameterDefinition.model_validate(compact)
    restored_from_json = ParameterDefinition.model_validate_json(
        definition.model_dump_json()
    )

    assert compact["value_type"]["shape"] == "scalar"
    assert compact["value_type"]["atom"]["type"]
    assert restored == definition
    assert restored_from_json == definition
    assert restored_from_json.model_dump_json() == definition.model_dump_json()


def test_persistable_value_type_wire_is_strict_and_schema_matches_it() -> None:
    definition = ParameterDefinition(
        id="value",
        value_type=Scalar(Float(minimum=0)),
    )
    value_type = definition.value_type

    assert isinstance(value_type, Scalar)
    assert isinstance(value_type.atom, Float)
    assert value_type.atom.minimum == 0.0
    with pytest.raises(ValidationError, match="unknown fields: garbage"):
        ParameterDefinition.model_validate(
            {
                "id": "value",
                "value_type": {
                    "shape": "scalar",
                    "atom": {"type": "bool", "garbage": True},
                },
            }
        )
    with pytest.raises(ValidationError, match="must require finite values"):
        ParameterDefinition(
            id="value",
            value_type=Scalar(Float(finite=False)),
        )
    with pytest.raises(ValidationError, match="supports only bool, int, float"):
        ParameterDefinition(
            id="value",
            value_type=Scalar(Payload("pulse_program")),
        )
    with pytest.raises(ValidationError, match="field 'finite' must be a bool"):
        ParameterDefinition.model_validate(
            {
                "id": "value",
                "value_type": {
                    "shape": "scalar",
                    "atom": {"type": "float", "finite": "false"},
                },
            }
        )
    with pytest.raises(ValidationError, match="field names must be strings"):
        ParameterDefinition.model_validate(
            {
                "id": "value",
                "value_type": {
                    "shape": "scalar",
                    "atom": {"type": "float", 1: "unexpected"},
                },
            }
        )

    integer_definition = ParameterDefinition.model_validate(
        {
            "id": "value",
            "value_type": {
                "shape": "scalar",
                "atom": {"type": "int", "minimum": 1.0},
            },
        }
    )
    assert isinstance(integer_definition.value_type, Scalar)
    assert isinstance(integer_definition.value_type.atom, Int)
    assert integer_definition.value_type.atom.minimum == 1

    schema = ParameterDefinition.model_json_schema(mode="validation")
    value_schema = schema["properties"]["value_type"]
    value_schema = schema["$defs"][value_schema["$ref"].rsplit("/", maxsplit=1)[-1]]
    assert len(value_schema["oneOf"]) == 3
    assert all(
        variant["additionalProperties"] is False for variant in value_schema["oneOf"]
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
            ParameterDefinition(id="value", value_type=value_type)


@pytest.mark.parametrize(
    "column",
    [
        TableColumn(
            id="id",
            value_type=Scalar(String()),
            required=False,
        ),
        TableColumn(
            id="id",
            value_type=Scalar(String(), nullable=True),
        ),
    ],
)
def test_parameter_table_primary_key_must_be_required_and_non_null(
    column: TableColumn,
) -> None:
    with pytest.raises(ValueError, match="required and non-null"):
        ParameterDefinition(
            id="values",
            value_type=Table(primary_key=("id",), columns=(column,)),
        )
