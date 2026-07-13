from __future__ import annotations

from scopecat._compiler.program import (
    TypedPointSource,
    bind_each,
    overlay_parameter_cell,
    set_state_field,
    typed_program,
)
from scopecat._relations import (
    RelationExpr,
    col,
    grid,
    linspace,
    literal_rows,
    outer,
    param,
    table,
)
from scopecat.models.parameter import Quantity
from scopecat.value_types import Quantity as QuantityType
from scopecat.value_types import Scalar, String
from scopecat.value_types import Table as TableType
from tests.support.experiment_preview import preview_contract
from tests.support.parameter_fixtures import parameters as _parameters


def _point_source(expr: RelationExpr) -> TypedPointSource:
    return TypedPointSource(
        expr=expr,
        value_type=TableType(columns=(), allow_extra_columns=True),
    )


def test_preview_state_changes_record_adjacent_desired_state_diffs() -> None:
    unchanged = typed_program(
        id="unchanged-state-patches",
        kind="problem",
        point_source=_point_source(grid(index=[0, 1])),
        state=[
            set_state_field(
                "drive-a",
                capability_id="drive",
                field_path="carrier_frequency",
                value=Quantity(value=5.0, unit="GHz"),
            )
        ],
    )
    swept = typed_program(
        id="swept-state-patches",
        kind="problem",
        point_source=_point_source(grid(frequency=linspace(5.0, 5.1, 2, unit="GHz"))),
        state=[
            set_state_field(
                "drive-a",
                capability_id="drive",
                field_path="carrier_frequency",
                value=col("frequency"),
            )
        ],
    )

    unchanged_preview = preview_contract(unchanged, _parameters())
    swept_preview = preview_contract(swept, _parameters())
    unchanged_patches = [
        (change.point_index, change.resource, change.field, change.before, change.after)
        for change in unchanged_preview.state_changes
    ]
    swept_patches = [
        (change.point_index, change.resource, change.field, change.before, change.after)
        for change in swept_preview.state_changes
    ]

    assert unchanged_patches == [
        (
            0,
            "drive-a",
            "drive.carrier_frequency",
            None,
            Quantity(value=5.0, unit="GHz"),
        )
    ]
    assert swept_patches == [
        (
            0,
            "drive-a",
            "drive.carrier_frequency",
            None,
            Quantity(value=5.0, unit="GHz"),
        ),
        (
            1,
            "drive-a",
            "drive.carrier_frequency",
            Quantity(value=5.0, unit="GHz"),
            Quantity(value=5.1, unit="GHz"),
        ),
    ]
    assert unchanged_patches != swept_patches


def test_preview_repeated_state_uses_outer_point_row() -> None:
    spec = typed_program(
        id="shared-lo-fixed-if-scan",
        kind="drive.shared_lo_scan",
        point_source=_point_source(
            grid(lo_frequency=linspace(4.9, 5.0, 2, unit="GHz"))
        ),
        state=[
            bind_each(
                table("drive_channels"),
                set_state_field(
                    col("resource_id"),
                    capability_id="drive",
                    field_path="carrier_frequency",
                    value=outer("lo_frequency") + col("fixed_if"),
                ),
            )
        ],
    )

    preview = preview_contract(spec, _parameters())

    assert [point.coordinates["lo_frequency"] for point in preview.points] == [
        Quantity(value=4.9, unit="GHz"),
        Quantity(value=5.0, unit="GHz"),
    ]
    assert [
        (change.point_index, change.resource, change.field, change.after)
        for change in preview.state_changes
    ] == [
        (0, "xy0", "drive.carrier_frequency", Quantity(value=5.0, unit="GHz")),
        (0, "xy1", "drive.carrier_frequency", Quantity(value=5.02, unit="GHz")),
        (1, "xy0", "drive.carrier_frequency", Quantity(value=5.1, unit="GHz")),
        (1, "xy1", "drive.carrier_frequency", Quantity(value=5.12, unit="GHz")),
    ]


def test_preview_selected_target_table_plans_simultaneous_resources() -> None:
    spec = typed_program(
        id="selected-readouts-with-shared-drives",
        kind="readout.selected_parallel_scan",
        point_source=_point_source(
            table("readout_devices")
            .join(
                literal_rows([{"device_id": "r1"}, {"device_id": "r0"}]),
                on={"device_id": "device_id"},
            )
            .sort("device_id")
        ),
        parameter_overlays=[
            overlay_parameter_cell(
                "readout_devices",
                key={"device_id": col("device_id")},
                key_types={"device_id": Scalar(String())},
                column_id="frequency",
                value=col("frequency") + Quantity(value=50, unit="MHz"),
                value_type=Scalar(QuantityType(unit="GHz")),
            )
        ],
        state=[
            set_state_field(
                col("resource_id"),
                capability_id="readout",
                field_path="frequency",
                value=param(
                    "readout_devices",
                    key={"device_id": col("device_id")},
                    column="frequency",
                ),
            ),
            bind_each(
                table("drive_channels"),
                set_state_field(
                    col("resource_id"),
                    capability_id="drive",
                    field_path="carrier_frequency",
                    value=outer("frequency") + col("fixed_if"),
                ),
            ),
        ],
    )

    preview = preview_contract(spec, _parameters())

    assert [point.coordinates["device_id"] for point in preview.points] == ["r0", "r1"]
    assert [
        (change.point_index, change.resource, change.field, change.after)
        for change in preview.state_changes
    ] == [
        (0, "readout-a", "readout.frequency", Quantity(value=6.0, unit="GHz")),
        (0, "xy0", "drive.carrier_frequency", Quantity(value=6.05, unit="GHz")),
        (0, "xy1", "drive.carrier_frequency", Quantity(value=6.07, unit="GHz")),
        (1, "readout-b", "readout.frequency", Quantity(value=6.15, unit="GHz")),
        (1, "xy0", "drive.carrier_frequency", Quantity(value=6.2, unit="GHz")),
        (1, "xy1", "drive.carrier_frequency", Quantity(value=6.22, unit="GHz")),
    ]
    assert preview.records == ()
