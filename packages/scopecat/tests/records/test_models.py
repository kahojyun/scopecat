from collections.abc import Callable
from dataclasses import dataclass

import pytest
from pydantic import BaseModel, ValidationError

from scopecat.config.documents import load_config_snapshot_document
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.value_types import (
    Bool,
    Entity,
    Float,
    Int,
    Payload,
    Scalar,
    String,
    Table,
    TableColumn,
)
from scopecat.kernel.value_types import Quantity as QuantityType
from scopecat.records.artifact import RunContentEntry
from scopecat.records.parameter import (
    ParameterCatalog,
    ParameterDefinition,
    ParameterSnapshot,
    ScalarParameterValue,
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


def _artifact_with_metadata(value: object) -> RunContentEntry:
    return RunContentEntry.model_validate(
        {"id": "artifact", "kind": "attachment", "metadata": {"value": value}}
    )


_METADATA_MODEL_FACTORIES: tuple[_MetadataModelFactory, ...] = (
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
    snapshot = load_config_snapshot_document(EXAMPLE_DIR / "config-snapshot.json")
    restored = assert_model_round_trip(snapshot)

    assert restored.parameter_snapshot.get("drive_frequency") is not None
    assert restored.topology.entity("q0") is not None


def test_run_request_records_operator_metadata() -> None:
    request = RunRequest(
        experiment_id="test.template",
        operator="alice",
        metadata={"sample": "q0"},
    )
    restored = assert_model_round_trip(
        request,
    )

    assert restored.operator == "alice"
    assert restored.metadata == {"sample": "q0"}


def test_run_request_records_canonical_scans_only() -> None:
    request = RunRequest(
        scans=[
            PointScanRecord(
                axis_id="drive_frequency",
                values=[5.0, 5.1],
            )
        ],
    )
    restored = assert_model_round_trip(
        request,
    )

    assert restored.scans == request.scans
    assert isinstance(restored.scans[0], PointScanRecord)
    assert restored.model_dump(mode="json")["scans"] == [
        {
            "kind": "point",
            "axis_id": "drive_frequency",
            "values": [5.0, 5.1],
        }
    ]
    with pytest.raises(ValidationError):
        RunRequest.model_validate(
            {
                "scans": [
                    {
                        "kind": "point",
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
                "scans": [
                    {
                        "kind": "point",
                        "axis_id": "drive_frequency",
                    }
                ],
            }
        )
    with pytest.raises(ValidationError):
        RunRequest.model_validate(
            {
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
            "inputs": {
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
                    "axis_id": "drive_frequency",
                    "center": {
                        "kind": "parameter",
                        "parameter_id": "drive_frequency",
                    },
                    "span": Quantity(value=100.0, unit="MHz"),
                    "points": 3,
                },
            ],
            "metadata": {"notebook": "02_define_experiment"},
        }
    )

    assert isinstance(request.inputs["subject"], RunRequestEntityRef)
    assert request.inputs["subject"] == RunRequestEntityRef(
        entity_id="q0",
        entity_kind="qubit",
    )
    assert request.model_dump(mode="json")["inputs"]["subject"] == {
        "kind": "entity",
        "entity_id": "q0",
        "entity_kind": "qubit",
        "metadata": {},
    }
    assert isinstance(request.inputs["frequency"], Quantity)
    scan = request.scans[0]
    assert isinstance(scan, AroundScanRecord)
    assert scan.center == RunRequestParameterValue(parameter_id="drive_frequency")
    assert scan.span == Quantity(value=100.0, unit="MHz")
    assert RunRequest.model_validate_json(request.model_dump_json()) == request


def test_run_request_does_not_guess_entities_from_business_mappings() -> None:
    request = RunRequest.model_validate(
        {
            "inputs": {"settings": {"id": "business-object"}},
        }
    )

    assert request.inputs["settings"] == {"id": "business-object"}
    assert request.model_dump(mode="json")["inputs"]["settings"] == {
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
                    "inputs": {"value": value},
                }
            )


def test_run_request_symbolic_values_are_closed_and_recursive() -> None:
    center = {
        "kind": "binary",
        "operator": "+",
        "left": {
            "kind": "parameter",
            "parameter_id": "frequency_offset",
        },
        "right": {
            "kind": "parameter_lookup",
            "table_id": "device_parameters",
            "key": {"subject": "q0"},
            "column": "frequency",
        },
    }
    scan = AroundScanRecord.model_validate(
        {
            "axis_id": "drive_frequency",
            "center": center,
            "span": Quantity(value=100.0, unit="MHz"),
            "points": 3,
        }
    )

    assert scan.model_dump(mode="json")["center"] == center
    assert AroundScanRecord.model_validate_json(scan.model_dump_json()) == scan


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("inputs", {"opaque": object()}),
        ("metadata", {"opaque": object()}),
    ],
)
def test_run_request_rejects_opaque_values_early(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError, match=r"unsupported .*run request"):
        RunRequest.model_validate({field: value})


def test_scan_records_reject_unknown_or_structured_scalar_values() -> None:
    with pytest.raises(ValidationError):
        AroundScanRecord.model_validate(
            {
                "axis_id": "drive_frequency",
                "center": {"kind": "unknown", "value": 5.0},
                "span": 1.0,
                "points": 3,
            }
        )
    with pytest.raises(ValidationError):
        PointScanRecord.model_validate(
            {
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
    )

    assert table.rows == ({"value": 1.0},)

    snapshot = ParameterSnapshot(id="snapshot", values=[table])
    assert ParameterSnapshot.model_validate_json(snapshot.model_dump_json()) == snapshot


def test_parameter_snapshot_uses_one_discriminated_namespace() -> None:
    snapshot = ParameterSnapshot(
        id="parameter-snapshot",
        values=[
            ScalarParameterValue(id="enabled", value=True),
            TableParameterValue(id="calibrations", rows=[{"id": "q0"}]),
        ],
    )

    restored = ParameterSnapshot.model_validate_json(snapshot.model_dump_json())

    assert isinstance(restored.get("enabled"), ScalarParameterValue)
    assert isinstance(restored.get("calibrations"), TableParameterValue)
    with pytest.raises(ValidationError, match="duplicate stored parameter value"):
        ParameterSnapshot(
            id="duplicate",
            values=[
                ScalarParameterValue(id="same", value=1),
                TableParameterValue(id="same"),
            ],
        )


def test_parameter_catalog_supports_scalar_and_table_shapes() -> None:
    catalog = ParameterCatalog(
        id="public-lab-catalog",
        definitions=[
            ParameterDefinition(
                id="enabled",
                value_type=Scalar(Bool()),
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
    calibration_points = restored.get("calibration_points")
    assert enabled is not None
    assert calibration_points is not None
    assert isinstance(enabled.value_type, Scalar)
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
        Scalar(String(choices=("a", "b"))),
        Scalar(Entity(entity_kind="qubit")),
        Scalar(
            QuantityType(
                dimension="frequency",
                unit="GHz",
                minimum=4.0,
                maximum=6.0,
            ),
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


def test_persistable_value_type_wire_is_strict() -> None:
    definition = ParameterDefinition(
        id="value",
        value_type=Scalar(Float(minimum=0)),
    )
    value_type = definition.value_type

    assert isinstance(value_type, Scalar)
    assert isinstance(value_type.atom, Float)
    assert value_type.atom.minimum == 0.0
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
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
    with pytest.raises(ValidationError, match="Input should be True"):
        ParameterDefinition.model_validate(
            {
                "id": "value",
                "value_type": {
                    "shape": "scalar",
                    "atom": {"type": "float", "finite": "false"},
                },
            }
        )
    with pytest.raises(ValidationError, match="valid integer"):
        ParameterDefinition.model_validate(
            {
                "id": "value",
                "value_type": {
                    "shape": "scalar",
                    "atom": {"type": "int", "minimum": 1.0},
                },
            }
        )
