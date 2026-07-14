from dataclasses import replace

import pytest

from scopecat.compiler.frontend.environment import validate_config_environment
from scopecat.compiler.linking.linked import link_program
from scopecat.compiler.linking.materialization import materialize_local_plan
from scopecat.compiler.relations.model import (
    RelationExpr,
    col,
    grid,
    literal_rows,
    point_col,
    table,
)
from scopecat.compiler.relations.verification import (
    RelationPlanVerificationError,
    RelationTypeBindings,
    RowType,
)
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.program import (
    overlay_parameter_cell,
    typed_program,
)
from scopecat.kernel.value_types import Quantity as QuantityType
from scopecat.kernel.value_types import Scalar, String
from scopecat.kernel.value_types import Table as TableType
from scopecat.records.parameter import Quantity
from tests.testkit.authoring import load_config
from tests.testkit.parameter_fixtures import PARAMETER_TYPES, parameters
from tests.testkit.relation_plans import (
    each_state,
    state_field,
)
from tests.testkit.relation_plans import (
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
        row["frequency"] for row in environment.parameters.table_rows("readout_devices")
    ]
    plan = materialize_local_plan(link_program(spec, environment))
    without_overlay = materialize_local_plan(
        link_program(replace(spec, parameter_overlays=()), environment)
    )

    point_0_rows = plan.points[0].parameters.table_rows("readout_devices")
    point_1_rows = plan.points[1].parameters.table_rows("readout_devices")
    assert point_0_rows[0]["frequency"] == (Quantity(value=5.9, unit="GHz"))
    assert point_0_rows[1]["frequency"] == (Quantity(value=6.1, unit="GHz"))
    assert point_1_rows[0]["frequency"] == (Quantity(value=5.95, unit="GHz"))
    assert point_1_rows[1]["frequency"] == (Quantity(value=6.2, unit="GHz"))
    assert [point.logical_id for point in plan.points] == [
        point.logical_id for point in without_overlay.points
    ]
    assert [
        row["frequency"] for row in environment.parameters.table_rows("readout_devices")
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

    plan = materialize_local_plan(link_program(spec, _environment()))

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

    plan = materialize_local_plan(link_program(spec, _environment()))

    assert [problem.code for problem in plan.problems] == [
        "experiment_parameter_overlay_table_missing"
    ]
