from dataclasses import replace

from scopecat._compiler.binding import bind_program
from scopecat._compiler.environment import validate_config_environment
from scopecat._compiler.program import (
    TypedPointSource,
    bind_each,
    overlay_parameter_cell,
    set_state_field,
    typed_program,
)
from scopecat._relations import RelationExpr, col, grid, literal_rows, outer, table
from scopecat.models.parameter import Quantity
from scopecat.value_types import Quantity as QuantityType
from scopecat.value_types import Scalar, String
from scopecat.value_types import Table as TableType
from tests.support.authoring import load_config
from tests.support.parameter_fixtures import parameters


def _point_source(expr: RelationExpr) -> TypedPointSource:
    return TypedPointSource(
        expr=expr,
        value_type=TableType(columns=(), allow_extra_columns=True),
    )


def _environment():
    return replace(
        validate_config_environment(load_config()),
        parameters=parameters(),
    )


def _frequency_overlay(*, key: object, value: object):
    return overlay_parameter_cell(
        "readout_devices",
        key={"device_id": key},
        key_types={"device_id": Scalar(String())},
        column_id="frequency",
        value=value,
        value_type=Scalar(QuantityType(unit="GHz")),
    )


def test_point_parameter_overlay_replaces_only_one_existing_cell() -> None:
    spec = typed_program(
        id="readout-frequency-overlay",
        kind="readout.frequency_scan",
        point_source=_point_source(
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
        ),
        parameter_overlays=[
            _frequency_overlay(key=col("device_id"), value=col("frequency"))
        ],
        state=[
            bind_each(
                table("readout_devices"),
                set_state_field(
                    col("resource_id"),
                    capability_id="readout",
                    field_path="frequency",
                    value=col("frequency"),
                    route_entities=(outer("device_id"),),
                ),
            )
        ],
    )

    plan = bind_program(spec, _environment())

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
    assert not hasattr(plan, "parameter_patches")


def test_point_parameter_overlay_reports_missing_row_without_partial_plan() -> None:
    spec = typed_program(
        id="missing-overlay-row",
        kind="problem",
        point_source=_point_source(grid(device_id=["missing"])),
        parameter_overlays=[
            _frequency_overlay(
                key=col("device_id"),
                value=Quantity(value=5.9, unit="GHz"),
            )
        ],
        state=[
            set_state_field(
                "readout-a",
                capability_id="readout",
                field_path="frequency",
                value=col("device_id"),
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
    spec = typed_program(
        id="invalid-overlay-value",
        kind="problem",
        point_source=_point_source(
            grid(device_id=["r0"], frequency=["not-a-frequency"])
        ),
        parameter_overlays=[
            _frequency_overlay(key=col("device_id"), value=col("frequency"))
        ],
    )

    plan = bind_program(spec, _environment())

    assert [problem.code for problem in plan.problems] == [
        "experiment_parameter_overlay_value_invalid"
    ]


def test_point_parameter_overlay_reports_missing_table() -> None:
    spec = typed_program(
        id="missing-overlay-table",
        kind="problem",
        point_source=_point_source(grid(device_id=["r0"])),
        parameter_overlays=[
            overlay_parameter_cell(
                "missing_table",
                key={"device_id": col("device_id")},
                key_types={"device_id": Scalar(String())},
                column_id="frequency",
                value=Quantity(value=5.9, unit="GHz"),
                value_type=Scalar(QuantityType(unit="GHz")),
            )
        ],
    )

    plan = bind_program(spec, _environment())

    assert [problem.code for problem in plan.problems] == [
        "experiment_parameter_overlay_table_missing"
    ]
