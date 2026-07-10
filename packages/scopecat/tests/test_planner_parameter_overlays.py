from scopecat._compiler.program import (
    bind_each,
    linked_program,
    overlay_parameter_cell,
    set_state,
)
from scopecat._planning.planner import build_planner_snapshot
from scopecat._relations import col, grid, literal_rows, outer, table
from scopecat.models.parameter import Quantity
from scopecat.value_types import Quantity as QuantityType
from scopecat.value_types import Scalar, String
from tests.support.experiment_preview import preview_result
from tests.support.parameter_fixtures import parameters


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
    spec = linked_program(
        id="readout-frequency-overlay",
        kind="readout.frequency_scan",
        points=literal_rows(
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
        ),
        parameter_overlays=[
            _frequency_overlay(key=col("device_id"), value=col("frequency"))
        ],
        state=[
            bind_each(
                table("readout_devices"),
                set_state(
                    col("resource_id"),
                    "readout.frequency",
                    col("frequency"),
                    route_entities=(outer("device_id"),),
                ),
            )
        ],
    )

    plan = build_planner_snapshot(spec, parameters())

    assert plan.point_parameters[0].tables["readout_devices"][0]["frequency"] == (
        Quantity(value=5.9, unit="GHz")
    )
    assert plan.point_parameters[0].tables["readout_devices"][1]["frequency"] == (
        Quantity(value=6.1, unit="GHz")
    )
    assert plan.point_parameters[1].tables["readout_devices"][0]["frequency"] == (
        Quantity(value=5.95, unit="GHz")
    )
    assert plan.point_parameters[1].tables["readout_devices"][1]["frequency"] == (
        Quantity(value=6.2, unit="GHz")
    )
    assert not hasattr(plan, "parameter_patches")


def test_point_parameter_overlay_reports_missing_row_without_partial_plan() -> None:
    spec = linked_program(
        id="missing-overlay-row",
        kind="diagnostic",
        points=grid(device_id=["missing"]),
        parameter_overlays=[
            _frequency_overlay(
                key=col("device_id"),
                value=Quantity(value=5.9, unit="GHz"),
            )
        ],
        state=[set_state("readout-a", "frequency", col("device_id"))],
    )

    preview, diagnostics = preview_result(spec, parameters())

    assert [diagnostic.code for diagnostic in diagnostics] == [
        "experiment_parameter_overlay_row_not_found"
    ]
    assert preview.state_changes == ()


def test_point_parameter_overlay_validates_value_against_catalog_type() -> None:
    spec = linked_program(
        id="invalid-overlay-value",
        kind="diagnostic",
        points=grid(device_id=["r0"], frequency=["not-a-frequency"]),
        parameter_overlays=[
            _frequency_overlay(key=col("device_id"), value=col("frequency"))
        ],
    )

    _preview, diagnostics = preview_result(spec, parameters())

    assert [diagnostic.code for diagnostic in diagnostics] == [
        "experiment_parameter_overlay_value_invalid"
    ]


def test_point_parameter_overlay_reports_missing_table() -> None:
    spec = linked_program(
        id="missing-overlay-table",
        kind="diagnostic",
        points=grid(device_id=["r0"]),
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

    _preview, diagnostics = preview_result(spec, parameters())

    assert [diagnostic.code for diagnostic in diagnostics] == [
        "experiment_parameter_overlay_table_missing"
    ]
