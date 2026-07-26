from __future__ import annotations

from scopecat.compiler.relations.verification import (
    RelationTypeBindings,
    RowType,
)
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.program import LogicalResourceRequirement
from scopecat.graph.relations.model import (
    CellValue,
    point_col,
)
from scopecat.graph.relations.point_domain import point_axis_values
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.resource_identity import logical_resource_port_id
from scopecat.kernel.state import StateValue
from scopecat.kernel.value_types import Int, Scalar
from scopecat.kernel.value_types import Quantity as QuantityType
from tests.testkit.materialized_effects import (
    config_with_physical_resources,
    materialized_effects_contract,
    materialized_state_fields,
)
from tests.testkit.parameter_fixtures import (
    PARAMETER_TYPES,
)
from tests.testkit.parameter_fixtures import (
    parameters as _parameters,
)
from tests.testkit.relation_plans import state_field
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
) -> RelationTypeBindings:
    return RelationTypeBindings(
        parameters=PARAMETER_TYPES,
        point_row=RowType.from_table(points.value_type),
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
