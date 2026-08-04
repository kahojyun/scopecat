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
from scopecat.records.run import RunStageLineage
from scopecat.records.run_request import (
    AxisAroundSourceRecord,
    AxisRangeSourceRecord,
    AxisRecord,
    AxisValuesSourceRecord,
    GridDomainRecord,
    PointCloudDomainRecord,
    PointPlanRecord,
    RunRequest,
    RunRequestEntityRef,
    RunRequestParameterLookupValue,
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
    assert restored.point_plan == PointPlanRecord()


def test_run_request_records_typed_stage_lineage() -> None:
    lineage = RunStageLineage(
        sequence_id="adaptive-sequence",
        index=2,
        previous_run_id="run-2",
    )

    restored = assert_model_round_trip(RunRequest(stage=lineage))

    assert restored.stage == lineage
    assert restored.metadata == {}
    with pytest.raises(ValidationError, match="first run stage"):
        RunStageLineage(
            sequence_id="adaptive-sequence",
            index=0,
            previous_run_id="run-previous",
        )
    with pytest.raises(ValidationError, match="later run stage"):
        RunStageLineage(sequence_id="adaptive-sequence", index=1)


def test_run_request_records_canonical_grid_axes_only() -> None:
    request = RunRequest(
        point_plan=PointPlanRecord(
            domain=GridDomainRecord(
                axes=[
                    AxisRecord(
                        axis_id="drive_frequency",
                        source=AxisValuesSourceRecord(values=[5.0, 5.1]),
                    )
                ]
            ),
        ),
    )
    restored = assert_model_round_trip(
        request,
    )

    assert restored.point_plan == request.point_plan
    assert isinstance(restored.point_plan.domain, GridDomainRecord)
    axis = restored.point_plan.domain.axes[0]
    assert isinstance(axis, AxisRecord)
    assert isinstance(axis.source, AxisValuesSourceRecord)
    assert restored.model_dump(mode="json")["point_plan"] == {
        "domain": {
            "kind": "grid",
            "axes": [
                {
                    "axis_id": "drive_frequency",
                    "source": {
                        "kind": "values",
                        "values": [5.0, 5.1],
                    },
                    "overlay": None,
                }
            ],
        },
        "repeat": 1,
        "repeat_mode": "point",
        "traversal": "forward",
    }
    with pytest.raises(ValidationError):
        RunRequest.model_validate(
            {
                "point_plan": {
                    "domain": {
                        "kind": "grid",
                        "axes": [
                            {
                                "axis_id": "drive_frequency",
                                "source": {
                                    "kind": "values",
                                    "values": [5.0],
                                },
                                "input_id": "frequencies",
                            }
                        ],
                    },
                },
            }
        )
    with pytest.raises(ValidationError):
        RunRequest.model_validate(
            {
                "point_plan": {
                    "domain": {
                        "kind": "grid",
                        "axes": [
                            {
                                "axis_id": "drive_frequency",
                                "source": {"kind": "values"},
                            }
                        ],
                    },
                },
            }
        )
    with pytest.raises(ValidationError):
        RunRequest.model_validate(
            {
                "point_plan": {
                    "domain": {
                        "kind": "grid",
                        "axes": [
                            {
                                "axis_id": "drive_frequency",
                                "source": {"kind": "unknown"},
                            }
                        ],
                    },
                },
            }
        )


def test_axis_range_sources_round_trip_numeric_and_quantity_endpoints() -> None:
    request = RunRequest(
        point_plan=PointPlanRecord(
            domain=GridDomainRecord(
                axes=[
                    AxisRecord(
                        axis_id="power",
                        source=AxisRangeSourceRecord(
                            start=Quantity(value=-30.0, unit="dBm"),
                            stop=Quantity(value=0.0, unit="dBm"),
                            points=61,
                        ),
                    ),
                    AxisRecord(
                        axis_id="gain",
                        source=AxisRangeSourceRecord(
                            start=-1,
                            stop=1.0,
                            points=3,
                        ),
                        overlay=RunRequestParameterLookupValue(
                            table_id="device_parameters",
                            key={"device": "q0"},
                            column="gain",
                        ),
                    ),
                ]
            ),
        )
    )

    restored = assert_model_round_trip(request)

    assert restored == request
    assert restored.model_dump(mode="json")["point_plan"]["domain"] == {
        "kind": "grid",
        "axes": [
            {
                "axis_id": "power",
                "source": {
                    "kind": "range",
                    "start": {"value": -30.0, "unit": "dBm"},
                    "stop": {"value": 0.0, "unit": "dBm"},
                    "points": 61,
                },
                "overlay": None,
            },
            {
                "axis_id": "gain",
                "source": {
                    "kind": "range",
                    "start": -1,
                    "stop": 1.0,
                    "points": 3,
                },
                "overlay": {
                    "kind": "parameter_lookup",
                    "table_id": "device_parameters",
                    "key": {"device": "q0"},
                    "column": "gain",
                },
            },
        ],
    }


def test_grid_domain_requires_nonempty_unique_axis_ids() -> None:
    source = AxisValuesSourceRecord(values=[1])
    with pytest.raises(ValidationError):
        GridDomainRecord(axes=[AxisRecord(axis_id="", source=source)])
    with pytest.raises(ValidationError, match="axis ids must be unique"):
        GridDomainRecord(
            axes=[
                AxisRecord(axis_id="frequency", source=source),
                AxisRecord(axis_id="frequency", source=source),
            ]
        )


def test_around_axis_overlay_must_also_be_its_center() -> None:
    center = RunRequestParameterLookupValue(
        table_id="device_parameters",
        key={"device": "q0"},
        column="frequency",
    )
    source = AxisAroundSourceRecord(
        center=center,
        span=Quantity(value=100.0, unit="MHz"),
        points=3,
    )

    assert AxisRecord(axis_id="frequency", source=source, overlay=center).overlay == (
        center
    )
    with pytest.raises(ValidationError, match="overlay must also be its center"):
        AxisRecord(
            axis_id="frequency",
            source=source,
            overlay=center.model_copy(update={"column": "other"}),
        )


def test_point_cloud_domain_round_trips_without_axis_mixing() -> None:
    request = RunRequest(
        point_plan=PointPlanRecord(
            domain=PointCloudDomainRecord(
                columns=["frequency", "power"],
                rows=[
                    {"frequency": 5.0, "power": -20.0},
                    {"frequency": 5.1, "power": -18.0},
                ],
            ),
        )
    )

    restored = assert_model_round_trip(request)

    assert isinstance(restored.point_plan.domain, PointCloudDomainRecord)
    assert restored.model_dump(mode="json")["point_plan"]["domain"] == {
        "kind": "points",
        "columns": ["frequency", "power"],
        "rows": [
            {"frequency": 5.0, "power": -20.0},
            {"frequency": 5.1, "power": -18.0},
        ],
    }


@pytest.mark.parametrize(
    "point_domain",
    [
        {
            "kind": "grid",
            "axes": [],
            "columns": ["frequency"],
            "rows": [{"frequency": 5.0}],
        },
        {
            "kind": "points",
            "columns": ["frequency"],
            "rows": [{"frequency": 5.0}],
            "axes": [],
        },
        {
            "kind": "grid",
            "axes": [
                {
                    "kind": "points",
                    "columns": ["frequency"],
                    "rows": [{"frequency": 5.0}],
                }
            ],
        },
    ],
)
def test_point_domain_rejects_mixed_grid_and_point_cloud_shapes(
    point_domain: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        RunRequest.model_validate({"point_plan": {"domain": point_domain}})


def test_point_cloud_domain_requires_exact_unique_columns() -> None:
    with pytest.raises(ValidationError, match="unique"):
        PointCloudDomainRecord(
            columns=["frequency", "frequency"],
            rows=[],
        )
    with pytest.raises(ValidationError, match="exactly"):
        PointCloudDomainRecord(
            columns=["frequency", "power"],
            rows=[{"frequency": 5.0}],
        )


def test_point_plan_policy_round_trips_with_its_base_domain() -> None:
    plan = PointPlanRecord(
        domain=GridDomainRecord(
            axes=[
                AxisRecord(
                    axis_id="frequency",
                    source=AxisValuesSourceRecord(values=[5.0, 5.1]),
                )
            ]
        ),
        repeat=3,
        repeat_mode="sweep",
        traversal="snake",
    )

    restored = assert_model_round_trip(RunRequest(point_plan=plan))

    assert restored.point_plan == plan


@pytest.mark.parametrize("repeat", [0, -1, 1.0, True])
def test_point_plan_repeat_requires_a_positive_strict_integer(repeat: object) -> None:
    with pytest.raises(ValidationError):
        PointPlanRecord.model_validate({"repeat": repeat})


def test_point_cloud_plan_rejects_snake_traversal() -> None:
    with pytest.raises(ValidationError, match="Cartesian grid"):
        PointPlanRecord(
            domain=PointCloudDomainRecord(
                columns=["frequency"],
                rows=[{"frequency": 5.0}],
            ),
            traversal="snake",
        )


@pytest.mark.parametrize(
    "domain",
    [
        GridDomainRecord(
            axes=[
                AxisRecord(
                    axis_id="repeat",
                    source=AxisValuesSourceRecord(values=[0, 1]),
                )
            ]
        ),
        PointCloudDomainRecord(
            columns=["repeat"],
            rows=[{"repeat": 0}],
        ),
    ],
)
def test_repeated_point_plan_reserves_the_repeat_coordinate(
    domain: GridDomainRecord | PointCloudDomainRecord,
) -> None:
    with pytest.raises(ValidationError, match="coordinate id 'repeat'"):
        PointPlanRecord(domain=domain, repeat=2)


def test_generated_axis_sources_require_quantity_spans_and_two_points() -> None:
    with pytest.raises(ValidationError):
        AxisAroundSourceRecord.model_validate(
            {
                "center": Quantity(value=-20.0, unit="dBm"),
                "span": 6.0,
                "points": 3,
            }
        )
    with pytest.raises(ValidationError):
        AxisRangeSourceRecord(
            start=Quantity(value=-30.0, unit="dBm"),
            stop=Quantity(value=0.0, unit="dBm"),
            points=1,
        )
    with pytest.raises(ValidationError):
        AxisRangeSourceRecord.model_validate(
            {
                "start": "-30",
                "stop": "0",
                "points": 3,
            }
        )
    with pytest.raises(ValidationError, match="both be quantities"):
        AxisRangeSourceRecord(
            start=Quantity(value=-30.0, unit="dBm"),
            stop=0.0,
            points=3,
        )
    with pytest.raises(ValidationError, match="compatible units"):
        AxisRangeSourceRecord(
            start=Quantity(value=0.0, unit="V"),
            stop=Quantity(value=1.0, unit="s"),
            points=3,
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
            "point_plan": {
                "domain": {
                    "kind": "grid",
                    "axes": [
                        {
                            "axis_id": "drive_frequency",
                            "source": {
                                "kind": "around",
                                "center": {
                                    "kind": "parameter",
                                    "parameter_id": "drive_frequency",
                                },
                                "span": Quantity(value=100.0, unit="MHz"),
                                "points": 3,
                            },
                        },
                    ],
                },
            },
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
    assert isinstance(request.point_plan.domain, GridDomainRecord)
    axis = request.point_plan.domain.axes[0]
    assert isinstance(axis.source, AxisAroundSourceRecord)
    assert axis.source.center == RunRequestParameterValue(
        parameter_id="drive_frequency"
    )
    assert axis.source.span == Quantity(value=100.0, unit="MHz")
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
    source = AxisAroundSourceRecord.model_validate(
        {
            "center": center,
            "span": Quantity(value=100.0, unit="MHz"),
            "points": 3,
        }
    )

    assert source.model_dump(mode="json")["center"] == center
    assert (
        AxisAroundSourceRecord.model_validate_json(source.model_dump_json()) == source
    )


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


def test_axis_sources_reject_unknown_or_structured_scalar_values() -> None:
    with pytest.raises(ValidationError):
        AxisAroundSourceRecord.model_validate(
            {
                "center": {"kind": "unknown", "value": 5.0},
                "span": 1.0,
                "points": 3,
            }
        )
    with pytest.raises(ValidationError):
        AxisValuesSourceRecord.model_validate(
            {
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
