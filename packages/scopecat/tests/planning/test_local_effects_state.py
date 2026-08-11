from __future__ import annotations

from testkit.bound_program import program_fixture
from testkit.expressions import state_property
from testkit.materialized_effects import (
    config_with_physical_resources,
    materialized_effects_contract,
    materialized_state_properties,
)
from testkit.parameter_fixtures import (
    parameters as _parameters,
)

from scopecat.compiler.bound_facts import LogicalResourceRequirement
from scopecat.compiler.point_domain import PointDomain
from scopecat.compiler.relations.verification import (
    ExpressionTypeBindings,
    RowType,
)
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.resource_identity import logical_resource_port_id
from scopecat.kernel.state import StateValue
from scopecat.kernel.value_data import CellValue
from scopecat.kernel.value_types import Int, Scalar
from scopecat.kernel.value_types import Quantity as QuantityType
from scopecat.program.expressions import (
    point_col,
)
from scopecat.program.point_domain import point_axis_values


def _state_literal(value: object) -> object:
    return value.root if isinstance(value, StateValue) else value


def _point_domain(
    column_id: str,
    value_type: Scalar,
    values: tuple[CellValue, ...],
) -> PointDomain:
    return PointDomain(
        axes=(point_axis_values(column_id, value_type, values),),
    )


def _point_bindings(
    points: PointDomain,
) -> ExpressionTypeBindings:
    return ExpressionTypeBindings(
        point_row=RowType.from_table(points.value_type),
    )


def test_materialized_effects_binds_desired_state_for_each_point() -> None:
    unchanged_points = _point_domain("index", Scalar(Int()), (0, 1))
    unchanged = program_fixture(
        point_domain=unchanged_points,
        resource_requirements=(
            LogicalResourceRequirement(
                port_id=logical_resource_port_id("drive"),
                interfaces=("test.drive/v1",),
            ),
        ),
        state=[
            state_property(
                "drive",
                interface_id="test.drive/v1",
                property_id="carrier_frequency",
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
    swept = program_fixture(
        point_domain=swept_points,
        resource_requirements=(
            LogicalResourceRequirement(
                port_id=logical_resource_port_id("drive"),
                interfaces=("test.drive/v1",),
            ),
        ),
        state=[
            state_property(
                "drive",
                interface_id="test.drive/v1",
                property_id="carrier_frequency",
                value=point_col(
                    "frequency",
                    Scalar(QuantityType(unit="GHz")),
                ),
                bindings=_point_bindings(swept_points),
            )
        ],
    )

    config = config_with_physical_resources({"drive-a": ("test.drive/v1",)})
    unchanged_preview = materialized_effects_contract(
        unchanged, _parameters(), config=config
    )
    swept_preview = materialized_effects_contract(swept, _parameters(), config=config)
    unchanged_state = [
        (
            point_index,
            state.instrument_id,
            f"{target.interface_id}.{target.property_id}",
            _state_literal(target.value),
        )
        for point_index, state, target in materialized_state_properties(
            unchanged_preview
        )
    ]
    swept_state = [
        (
            point_index,
            state.instrument_id,
            f"{target.interface_id}.{target.property_id}",
            _state_literal(target.value),
        )
        for point_index, state, target in materialized_state_properties(swept_preview)
    ]

    assert unchanged_state == [
        (
            0,
            "drive-a",
            "test.drive/v1.carrier_frequency",
            Quantity(value=5.0, unit="GHz"),
        ),
        (
            1,
            "drive-a",
            "test.drive/v1.carrier_frequency",
            Quantity(value=5.0, unit="GHz"),
        ),
    ]
    assert swept_state == [
        (
            0,
            "drive-a",
            "test.drive/v1.carrier_frequency",
            Quantity(value=5.0, unit="GHz"),
        ),
        (
            1,
            "drive-a",
            "test.drive/v1.carrier_frequency",
            Quantity(value=5.1, unit="GHz"),
        ),
    ]
    assert unchanged_state != swept_state
