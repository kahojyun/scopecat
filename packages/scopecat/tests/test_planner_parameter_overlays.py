from dataclasses import replace

import pytest

from scopecat._compiler.binding import bind_program
from scopecat._compiler.environment import validate_config_environment
from scopecat._compiler.point_domain import PointDomain
from scopecat._compiler.program import (
    overlay_parameter_cell,
    typed_program,
)
from scopecat._relation_verification import (
    RelationPlanVerificationError,
    RelationTypeBindings,
    RowType,
)
from scopecat._relations import RelationExpr, col, grid, literal_rows, point_col, table
from scopecat.models.parameter import Quantity
from scopecat.value_types import Quantity as QuantityType
from scopecat.value_types import Scalar, String
from scopecat.value_types import Table as TableType
from tests.support.authoring import load_config
from tests.support.parameter_fixtures import PARAMETER_TYPES, parameters
from tests.support.relation_plans import (
    each_state,
    state_field,
)
from tests.support.relation_plans import (
    point_domain as verified_point_domain,
)

_PARAMETER_TYPES = PARAMETER_TYPES


def _point_domain(expr: RelationExpr) -> PointDomain:
    return verified_point_domain(
        expr,
        bindings=RelationTypeBindings(parameters=_PARAMETER_TYPES),
    )


def _point_bindings(points: PointDomain) -> RelationTypeBindings:
    return RelationTypeBindings(
        parameters=_PARAMETER_TYPES,
        point_row=RowType.from_table(points.value_type),
    )


def _state_bindings(points: PointDomain, table_id: str) -> RelationTypeBindings:
    table_type = _PARAMETER_TYPES[table_id]
    assert isinstance(table_type, TableType)
    return replace(
        _point_bindings(points),
        current_row=RowType.from_table(table_type),
    )


def _environment():
    return replace(
        validate_config_environment(load_config()),
        parameters=parameters(),
    )


def _frequency_overlay(
    *,
    key: object,
    value: object,
    bindings: RelationTypeBindings,
):
    return overlay_parameter_cell(
        "readout_devices",
        key={"device_id": key},
        key_types={"device_id": Scalar(String())},
        column_id="frequency",
        value=value,
        value_type=Scalar(QuantityType(unit="GHz")),
        bindings=bindings,
    )


def test_point_parameter_overlay_replaces_only_one_existing_cell() -> None:
    points = _point_domain(
        literal_rows(
            [
                {
                    "device_id": "r0",
                    "frequency": Quantity(value=5_900, unit="MHz"),
                },
                {
                    "device_id": "r1",
                    "frequency": Quantity(value=6_200, unit="MHz"),
                },
            ]
        )
    )
    point_bindings = _point_bindings(points)
    state_bindings = _state_bindings(points, "readout_devices")
    spec = typed_program(
        id="readout-frequency-overlay",
        kind="readout.frequency_scan",
        point_domain=points,
        parameter_overlays=[
            _frequency_overlay(
                key=point_col("device_id"),
                value=point_col("frequency"),
                bindings=point_bindings,
            )
        ],
        state=[
            each_state(
                table("readout_devices"),
                state_field(
                    col("resource_id"),
                    capability_id="readout",
                    field_path="frequency",
                    value=col("frequency"),
                    route_entities=(point_col("device_id"),),
                    bindings=state_bindings,
                ),
                bindings=point_bindings,
            )
        ],
    )

    environment = _environment()
    base_frequencies = [
        row["frequency"] for row in environment.parameters.tables["readout_devices"]
    ]
    plan = bind_program(spec, environment)
    without_overlay = bind_program(
        spec.model_copy(update={"parameter_overlays": ()}),
        environment,
    )

    assert plan.points[0].parameters.tables["readout_devices"][0]["frequency"] == (
        Quantity(value=5.9, unit="GHz")
    )
    assert plan.points[0].parameters.tables["readout_devices"][1]["frequency"] == (
        Quantity(value=6.1, unit="GHz")
    )
    assert plan.points[1].parameters.tables["readout_devices"][0]["frequency"] == (
        Quantity(value=5.95, unit="GHz")
    )
    assert plan.points[1].parameters.tables["readout_devices"][1]["frequency"] == (
        Quantity(value=6.2, unit="GHz")
    )
    assert [point.logical_id for point in plan.points] == [
        point.logical_id for point in without_overlay.points
    ]
    assert [
        row["frequency"] for row in environment.parameters.tables["readout_devices"]
    ] == base_frequencies
    assert not hasattr(plan, "parameter_patches")


def test_point_parameter_overlay_reports_missing_row_without_partial_plan() -> None:
    points = _point_domain(grid(device_id=["missing"]))
    bindings = _point_bindings(points)
    spec = typed_program(
        id="missing-overlay-row",
        kind="problem",
        point_domain=points,
        parameter_overlays=[
            _frequency_overlay(
                key=point_col("device_id"),
                value=Quantity(value=5.9, unit="GHz"),
                bindings=bindings,
            )
        ],
        state=[
            state_field(
                "source-0",
                capability_id="set_frequency",
                field_path="frequency",
                value=point_col("device_id"),
                bindings=bindings,
            )
        ],
    )

    plan = bind_program(spec, _environment())

    assert [problem.code for problem in plan.problems] == [
        "experiment_parameter_overlay_row_not_found"
    ]
    assert plan.points == ()
    assert plan.records == ()
    assert plan.expected_dataset_schema is None
    assert plan.state_changes == ()


def test_point_parameter_overlay_validates_value_against_catalog_type() -> None:
    points = _point_domain(grid(device_id=["r0"], frequency=["not-a-frequency"]))

    with pytest.raises(RelationPlanVerificationError) as error:
        _frequency_overlay(
            key=point_col("device_id"),
            value=point_col("frequency"),
            bindings=_point_bindings(points),
        )

    assert error.value.code == "incompatible_result_type"


def test_point_parameter_overlay_reports_missing_table() -> None:
    points = _point_domain(grid(device_id=["r0"]))
    bindings = _point_bindings(points)
    spec = typed_program(
        id="missing-overlay-table",
        kind="problem",
        point_domain=points,
        parameter_overlays=[
            overlay_parameter_cell(
                "missing_table",
                key={"device_id": point_col("device_id")},
                key_types={"device_id": Scalar(String())},
                column_id="frequency",
                value=Quantity(value=5.9, unit="GHz"),
                value_type=Scalar(QuantityType(unit="GHz")),
                bindings=bindings,
            )
        ],
    )

    plan = bind_program(spec, _environment())

    assert [problem.code for problem in plan.problems] == [
        "experiment_parameter_overlay_table_missing"
    ]
