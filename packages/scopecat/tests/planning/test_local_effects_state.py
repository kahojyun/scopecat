from __future__ import annotations

from dataclasses import replace

from scopecat.compiler.relations.model import (
    CellValue,
    RowScopeId,
    col,
    point_col,
    table,
)
from scopecat.compiler.relations.point_domain import point_axis_values
from scopecat.compiler.relations.verification import (
    RelationTypeBindings,
    RowType,
)
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.program import LogicalResourceRequirement
from scopecat.kernel.resource_identity import logical_resource_port_id
from scopecat.kernel.state import StateValue
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import Int, Scalar
from scopecat.kernel.value_types import Quantity as QuantityType
from scopecat.kernel.value_types import Table as TableType
from scopecat.records.parameter import Quantity
from tests.testkit.materialized_effects import (
    config_with_physical_resources,
    materialized_effects_contract,
    materialized_state_fields,
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
from tests.testkit.typed_program import typed_program


def _state_literal(value: object) -> object:
    return value.root if isinstance(value, StateValue) else value


def _point_domain(
    column_id: str,
    value_type: Scalar,
    values: tuple[CellValue, ...],
) -> PointDomain:
    return PointDomain(
        root=point_axis_values(column_id, value_type, values),
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
    row_scope_id: RowScopeId,
    lookup: bool = False,
) -> RelationTypeBindings:
    table_type = PARAMETER_TYPES[table_id]
    assert isinstance(table_type, TableType)
    return replace(
        _point_bindings(points, lookup=lookup),
        row_arguments={row_scope_id: RowType.from_table(table_type)},
    )


def test_materialized_effects_binds_desired_state_for_each_point() -> None:
    unchanged_points = _point_domain("index", Scalar(Int()), (0, 1))
    unchanged = typed_program(
        id="unchanged-state-patches",
        kind="problem",
        point_domain=unchanged_points,
        resource_requirements=(
            LogicalResourceRequirement(
                port_id=logical_resource_port_id("drive"),
                capabilities=("drive",),
            ),
        ),
        state=[
            state_field(
                "drive",
                capability_id="drive",
                field_path="carrier_frequency",
                value=Quantity(value=5.0, unit="GHz"),
                bindings=_point_bindings(unchanged_points),
            )
        ],
    )
    swept_points = _point_domain(
        "frequency",
        Scalar(QuantityType(unit="GHz")),
        (
            Quantity(value=5.0, unit="GHz"),
            Quantity(value=5.1, unit="GHz"),
        ),
    )
    swept = typed_program(
        id="swept-state-patches",
        kind="problem",
        point_domain=swept_points,
        resource_requirements=(
            LogicalResourceRequirement(
                port_id=logical_resource_port_id("drive"),
                capabilities=("drive",),
            ),
        ),
        state=[
            state_field(
                "drive",
                capability_id="drive",
                field_path="carrier_frequency",
                value=point_col("frequency"),
                bindings=_point_bindings(swept_points),
            )
        ],
    )

    config = config_with_physical_resources({"drive-a": ("drive",)})
    unchanged_preview = materialized_effects_contract(
        unchanged, _parameters(), config=config
    )
    swept_preview = materialized_effects_contract(swept, _parameters(), config=config)
    unchanged_state = [
        (
            point_index,
            state.instrument_id,
            f"{field.capability_id}.{field.field_path}",
            _state_literal(field.value),
        )
        for point_index, state, field in materialized_state_fields(unchanged_preview)
    ]
    swept_state = [
        (
            point_index,
            state.instrument_id,
            f"{field.capability_id}.{field.field_path}",
            _state_literal(field.value),
        )
        for point_index, state, field in materialized_state_fields(swept_preview)
    ]

    assert unchanged_state == [
        (
            0,
            "drive-a",
            "drive.carrier_frequency",
            Quantity(value=5.0, unit="GHz"),
        ),
        (
            1,
            "drive-a",
            "drive.carrier_frequency",
            Quantity(value=5.0, unit="GHz"),
        ),
    ]
    assert swept_state == [
        (
            0,
            "drive-a",
            "drive.carrier_frequency",
            Quantity(value=5.0, unit="GHz"),
        ),
        (
            1,
            "drive-a",
            "drive.carrier_frequency",
            Quantity(value=5.1, unit="GHz"),
        ),
    ]
    assert unchanged_state != swept_state


def test_materialized_effects_repeated_state_uses_outer_point_row() -> None:
    points = _point_domain(
        "lo_frequency",
        Scalar(QuantityType(unit="GHz")),
        (
            Quantity(value=4.9, unit="GHz"),
            Quantity(value=5.0, unit="GHz"),
        ),
    )
    point_bindings = _point_bindings(points)
    row_scope = RowScopeId(SymbolId(local_id="drive-channel-row"))
    spec = typed_program(
        id="shared-lo-fixed-if-scan",
        kind="drive.shared_lo_scan",
        point_domain=points,
        resource_requirements=(
            LogicalResourceRequirement(
                port_id=logical_resource_port_id("drive"),
                capabilities=("drive",),
            ),
        ),
        state=[
            each_state(
                table("drive_channels").filter(
                    col("resource_id", row_scope_id=row_scope).eq("xy0"),
                    row_scope_id=row_scope,
                ),
                state_field(
                    "drive",
                    capability_id="drive",
                    field_path="carrier_frequency",
                    value=point_col("lo_frequency")
                    + col("fixed_if", row_scope_id=row_scope),
                    bindings=_state_bindings(
                        points,
                        "drive_channels",
                        row_scope_id=row_scope,
                    ),
                ),
                row_scope_id=row_scope,
                bindings=point_bindings,
            )
        ],
    )

    preview = materialized_effects_contract(
        spec,
        _parameters(),
        config=config_with_physical_resources({"xy0": ("drive",)}),
    )

    assert [point.coordinates["lo_frequency"] for point in preview.points] == [
        Quantity(value=4.9, unit="GHz"),
        Quantity(value=5.0, unit="GHz"),
    ]
    assert [
        (
            point_index,
            state.instrument_id,
            f"{field.capability_id}.{field.field_path}",
            _state_literal(field.value),
        )
        for point_index, state, field in materialized_state_fields(preview)
    ] == [
        (0, "xy0", "drive.carrier_frequency", Quantity(value=5.0, unit="GHz")),
        (1, "xy0", "drive.carrier_frequency", Quantity(value=5.1, unit="GHz")),
    ]
