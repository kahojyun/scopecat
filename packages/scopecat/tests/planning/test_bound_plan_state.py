from __future__ import annotations

from dataclasses import replace

from scopecat.compiler.relations.model import (
    RelationExpr,
    col,
    grid,
    linspace,
    literal_rows,
    param,
    point_col,
    table,
)
from scopecat.compiler.relations.verification import (
    RelationTypeBindings,
    RowType,
)
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.program import (
    overlay_parameter_cell,
    typed_program,
)
from scopecat.kernel.state import StateValue
from scopecat.kernel.value_types import Quantity as QuantityType
from scopecat.kernel.value_types import Scalar, String
from scopecat.kernel.value_types import Table as TableType
from scopecat.records.parameter import Quantity
from tests.testkit.bound_plan import (
    bound_plan_contract,
    config_with_physical_resources,
)
from tests.testkit.parameter_fixtures import (
    PARAMETER_TYPES,
    READOUT_FREQUENCY_LOOKUP,
)
from tests.testkit.parameter_fixtures import (
    parameters as _parameters,
)
from tests.testkit.relation_plans import (
    each_state,
    state_field,
)
from tests.testkit.relation_plans import (
    point_domain as verified_point_domain,
)


def _state_literal(value: object) -> object:
    return value.root if isinstance(value, StateValue) else value


def _point_domain(expr: RelationExpr) -> PointDomain:
    return verified_point_domain(
        expr,
        bindings=RelationTypeBindings(parameters=PARAMETER_TYPES),
    )


def _point_bindings(
    points: PointDomain,
    *,
    lookup: bool = False,
) -> RelationTypeBindings:
    return RelationTypeBindings(
        parameters=PARAMETER_TYPES,
        parameter_lookups=((READOUT_FREQUENCY_LOOKUP,) if lookup else ()),
        point_row=RowType.from_table(points.value_type),
    )


def _state_bindings(
    points: PointDomain,
    table_id: str,
    *,
    lookup: bool = False,
) -> RelationTypeBindings:
    table_type = PARAMETER_TYPES[table_id]
    assert isinstance(table_type, TableType)
    return replace(
        _point_bindings(points, lookup=lookup),
        current_row=RowType.from_table(table_type),
    )


def test_bound_plan_state_changes_record_adjacent_desired_state_diffs() -> None:
    unchanged_points = _point_domain(grid(index=[0, 1]))
    unchanged = typed_program(
        id="unchanged-state-patches",
        kind="problem",
        point_domain=unchanged_points,
        state=[
            state_field(
                "drive-a",
                capability_id="drive",
                field_path="carrier_frequency",
                value=Quantity(value=5.0, unit="GHz"),
                bindings=_point_bindings(unchanged_points),
            )
        ],
    )
    swept_points = _point_domain(grid(frequency=linspace(5.0, 5.1, 2, unit="GHz")))
    swept = typed_program(
        id="swept-state-patches",
        kind="problem",
        point_domain=swept_points,
        state=[
            state_field(
                "drive-a",
                capability_id="drive",
                field_path="carrier_frequency",
                value=point_col("frequency"),
                bindings=_point_bindings(swept_points),
            )
        ],
    )

    config = config_with_physical_resources({"drive-a": ("drive",)})
    unchanged_preview = bound_plan_contract(unchanged, _parameters(), config=config)
    swept_preview = bound_plan_contract(swept, _parameters(), config=config)
    unchanged_patches = [
        (
            change.point_index,
            change.resource_id.value,
            change.field,
            _state_literal(change.before),
            _state_literal(change.after),
        )
        for change in unchanged_preview.state_changes
    ]
    swept_patches = [
        (
            change.point_index,
            change.resource_id.value,
            change.field,
            _state_literal(change.before),
            _state_literal(change.after),
        )
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


def test_bound_plan_repeated_state_uses_outer_point_row() -> None:
    points = _point_domain(grid(lo_frequency=linspace(4.9, 5.0, 2, unit="GHz")))
    point_bindings = _point_bindings(points)
    spec = typed_program(
        id="shared-lo-fixed-if-scan",
        kind="drive.shared_lo_scan",
        point_domain=points,
        state=[
            each_state(
                table("drive_channels"),
                state_field(
                    col("resource_id"),
                    capability_id="drive",
                    field_path="carrier_frequency",
                    value=point_col("lo_frequency") + col("fixed_if"),
                    bindings=_state_bindings(points, "drive_channels"),
                ),
                bindings=point_bindings,
            )
        ],
    )

    preview = bound_plan_contract(
        spec,
        _parameters(),
        config=config_with_physical_resources({"xy0": ("drive",), "xy1": ("drive",)}),
    )

    assert [point.coordinates["lo_frequency"] for point in preview.points] == [
        Quantity(value=4.9, unit="GHz"),
        Quantity(value=5.0, unit="GHz"),
    ]
    assert [
        (
            change.point_index,
            change.resource_id.value,
            change.field,
            _state_literal(change.after),
        )
        for change in preview.state_changes
    ] == [
        (0, "xy0", "drive.carrier_frequency", Quantity(value=5.0, unit="GHz")),
        (0, "xy1", "drive.carrier_frequency", Quantity(value=5.02, unit="GHz")),
        (1, "xy0", "drive.carrier_frequency", Quantity(value=5.1, unit="GHz")),
        (1, "xy1", "drive.carrier_frequency", Quantity(value=5.12, unit="GHz")),
    ]


def test_bound_plan_selected_target_table_plans_simultaneous_resources() -> None:
    points = _point_domain(
        table("readout_devices")
        .join(
            literal_rows([{"device_id": "r1"}, {"device_id": "r0"}]),
            on={"device_id": "device_id"},
        )
        .sort("device_id")
    )
    point_bindings = _point_bindings(points, lookup=True)
    spec = typed_program(
        id="selected-readouts-with-shared-drives",
        kind="readout.selected_parallel_scan",
        point_domain=points,
        parameter_overlays=[
            overlay_parameter_cell(
                "readout_devices",
                key={"device_id": point_col("device_id")},
                key_types={"device_id": Scalar(String())},
                column_id="frequency",
                value=point_col("frequency") + Quantity(value=50, unit="MHz"),
                value_type=Scalar(QuantityType(unit="GHz")),
                bindings=point_bindings,
            )
        ],
        state=[
            state_field(
                point_col("resource_id"),
                capability_id="readout",
                field_path="frequency",
                value=param(
                    "readout_devices",
                    key={"device_id": point_col("device_id")},
                    column="frequency",
                ),
                bindings=point_bindings,
            ),
            each_state(
                table("drive_channels"),
                state_field(
                    col("resource_id"),
                    capability_id="drive",
                    field_path="carrier_frequency",
                    value=point_col("frequency") + col("fixed_if"),
                    bindings=_state_bindings(
                        points,
                        "drive_channels",
                        lookup=True,
                    ),
                ),
                bindings=point_bindings,
            ),
        ],
    )

    preview = bound_plan_contract(
        spec,
        _parameters(),
        config=config_with_physical_resources(
            {
                "readout-a": ("readout",),
                "readout-b": ("readout",),
                "xy0": ("drive",),
                "xy1": ("drive",),
            }
        ),
    )

    assert [point.coordinates["device_id"] for point in preview.points] == ["r0", "r1"]
    assert [
        (
            change.point_index,
            change.resource_id.value,
            change.field,
            _state_literal(change.after),
        )
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
