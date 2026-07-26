from __future__ import annotations

from typing import cast

import pytest

from scopecat.compiler.relations.context import ParameterRelationData
from scopecat.compiler.relations.uses import RelationUse, relation_use
from scopecat.compiler.relations.verification import RelationTypeBindings
from scopecat.compiler.semantic.value_expressions import (
    ScalarValueExpr,
    verify_scalar_value_expr,
)
from scopecat.compiler.typed.iteration import (
    analyze_point_iteration_layout,
)
from scopecat.compiler.typed.point_domain import (
    CompilerPointDomainExpr,
    PointDomain,
    VerifiedPointDomain,
    materialize_point_domain,
    verify_point_domain,
)
from scopecat.graph.relations.model import (
    CellValue,
    ScalarExpr,
    lit,
    param,
)
from scopecat.graph.relations.point_domain import (
    PointAxis,
    point_axis_linear,
    point_axis_values,
    point_product,
)
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.value_types import (
    Int,
    Scalar,
)
from scopecat.kernel.value_types import (
    Quantity as QuantityType,
)

_INT = Scalar(Int())
_FREQUENCY = Scalar(QuantityType(unit="GHz"))
_SPAN = Quantity(value=2.0, unit="GHz")


def _center(
    expression: ScalarExpr,
    *,
    bindings: RelationTypeBindings | None = None,
) -> RelationUse[ScalarValueExpr]:
    return relation_use(
        verify_scalar_value_expr(
            expression,
            bindings=bindings or RelationTypeBindings(),
            expected_type=_FREQUENCY,
        )
    )


def _verify(
    root: CompilerPointDomainExpr,
    *,
    program_id: str,
) -> VerifiedPointDomain:
    return verify_point_domain(PointDomain(root), program_id=program_id)


def _values_axis(
    axis_id: str,
    value_type: Scalar,
    values: tuple[CellValue, ...],
) -> PointAxis[RelationUse[ScalarValueExpr]]:
    return cast(
        "PointAxis[RelationUse[ScalarValueExpr]]",
        point_axis_values(axis_id, value_type, values),
    )


def test_explicit_axes_project_exact_product_strides_and_partitions() -> None:
    verified = _verify(
        point_product(
            _values_axis("slow", _INT, (10, 20)),
            _values_axis("fast", _INT, (1, 2, 3)),
        ),
        program_id="explicit-product",
    )

    layout = analyze_point_iteration_layout(verified)

    assert tuple(axis.id for axis in layout.axes) == ("slow", "fast")
    slow = layout.axis("slow")
    fast = layout.axis("fast")
    assert slow is not None
    assert slow.values == (10, 20)
    assert slow.repeat_each == 3
    assert fast is not None
    assert fast.values == (1, 2, 3)
    assert fast.repeat_each == 1
    assert layout.partition(("slow",), range(6)) == ((0, 1, 2), (3, 4, 5))


def test_literal_center_linear_axis_has_lazy_known_exact_values() -> None:
    verified = _verify(
        point_axis_linear(
            "frequency",
            _FREQUENCY,
            _center(lit(Quantity(value=5.0, unit="GHz"))),
            _SPAN,
            3,
        ),
        program_id="literal-linear",
    )

    layout = analyze_point_iteration_layout(verified)

    assert tuple(axis.id for axis in layout.axes) == ("frequency",)
    frequency = layout.axis("frequency")
    assert frequency is not None
    assert frequency.values_at(range(3)) == (
        Quantity(value=4.0, unit="GHz"),
        Quantity(value=5.0, unit="GHz"),
        Quantity(value=6.0, unit="GHz"),
    )
    assert frequency.repeat_each == 1


def test_parameter_center_linear_axis_uses_materialized_partition_fallback() -> None:
    verified = _verify(
        point_axis_linear(
            "frequency",
            _FREQUENCY,
            _center(
                param("center"),
                bindings=RelationTypeBindings(parameters={"center": _FREQUENCY}),
            ),
            _SPAN,
            3,
        ),
        program_id="parameter-linear",
    )
    layout = analyze_point_iteration_layout(verified)

    assert layout.axes == ()
    assert layout.axis("frequency") is None
    with pytest.raises(KeyError, match="materialized axis value"):
        layout.partition(("frequency",), range(3))

    materialized = materialize_point_domain(
        verified,
        ParameterRelationData(scalars={"center": Quantity(value=5.0, unit="GHz")}),
    )
    rows = {point.logical_ordinal: point.row for point in materialized.points}

    assert layout.partition(("frequency",), range(3), rows=rows) == (
        (0,),
        (1,),
        (2,),
    )
