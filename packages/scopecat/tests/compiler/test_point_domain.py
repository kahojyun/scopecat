"""Symbolic and materialized point-domain semantics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from scopecat.compiler.point_domain import (
    MaterializedPoint,
    MaterializedPointDomain,
    PointDomain,
    PointDomainEvaluationError,
    PointDomainVerificationError,
    VerifiedPointDomain,
    materialize_point_domain,
    verify_point_domain,
)
from scopecat.compiler.relations.context import ParameterRelationData
from scopecat.compiler.relations.verification import (
    ExpressionTypeBindings,
    RowType,
    verify_scalar_expression,
)
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.point_identity import LogicalPointId, PointDomainId
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.value_data import CellValue
from scopecat.kernel.value_types import (
    Entity,
    Int,
    Scalar,
    TableColumn,
)
from scopecat.kernel.value_types import (
    Quantity as QuantityType,
)
from scopecat.kernel.value_validation import ValueValidationError
from scopecat.program.expressions import (
    ScalarExpr,
    as_scalar_expr,
    input_ref,
    param,
    point_col,
)
from scopecat.program.point_domain import (
    PointAxis,
    iter_point_axis_linear,
    point_axis_linear,
    point_axis_linear_value,
    point_axis_values,
)

_INT = Scalar(Int())
_TIME = Scalar(QuantityType(dimension="time", unit="ns"))
_ENTITY = Scalar(Entity("qubit"))

type _CenterUse = ScalarExpr


def verified_scalar_expr(
    expression: object,
    *,
    bindings: ExpressionTypeBindings | None = None,
    expected_type: Scalar,
) -> ScalarExpr:
    return verify_scalar_expression(
        as_scalar_expr(expression),
        bindings=bindings or ExpressionTypeBindings(),
        expected_type=expected_type,
    )


def _quantity(value: float, unit: str = "ns") -> Quantity:
    return Quantity(value=value, unit=unit)


def _axis(
    column_id: str,
    values: Sequence[CellValue],
    *,
    value_type: Scalar = _INT,
) -> PointAxis[_CenterUse]:
    return point_axis_values(column_id, value_type, tuple(values))


def _domain(
    values: Sequence[CellValue],
    *,
    domain_id: str = "root",
    value_type: Scalar = _INT,
) -> PointDomain:
    return PointDomain(
        axes=(_axis("x", values, value_type=value_type),),
        id=domain_id,
    )


def _verify(
    domain: PointDomain, *, program_id: str = "experiment"
) -> VerifiedPointDomain:
    return verify_point_domain(domain, program_id=program_id)


def _materialize(
    domain: PointDomain,
    *,
    program_id: str = "experiment",
    params: ParameterRelationData | None = None,
):
    return materialize_point_domain(
        _verify(domain, program_id=program_id),
        params or ParameterRelationData(),
    )


@settings(max_examples=50)
@given(values=st.lists(st.integers(min_value=-5, max_value=5), max_size=16))
def test_explicit_axis_identity_is_exact_ordinal_and_repeatable(
    values: list[int],
) -> None:
    first = _materialize(_domain(values))
    repeated = _materialize(_domain(values))

    assert len(first.points) == len(values)
    assert [point.logical_ordinal for point in first.points] == list(range(len(values)))
    assert [point.row["x"] for point in first.points] == values
    assert [point.logical_id for point in first.points] == [
        point.logical_id for point in repeated.points
    ]


def test_unit_materializes_one_empty_point() -> None:
    verified = _verify(PointDomain(axes=()), program_id="program")
    materialized = materialize_point_domain(verified, ParameterRelationData())

    assert verified.cardinality == 1
    assert [point.row for point in materialized.points] == [{}]


def test_zero_length_explicit_axis_remains_an_empty_domain() -> None:
    verified = _verify(_domain(()), program_id="program")
    materialized = materialize_point_domain(verified, ParameterRelationData())

    assert verified.cardinality == 0
    assert materialized.points == ()


def test_product_materialization_is_left_major() -> None:
    domain = PointDomain(
        axes=(
            _axis("left", (1, 2)),
            _axis("right", (3, 4)),
        )
    )

    materialized = _materialize(domain)

    assert len(materialized.points) == 4
    assert [point.row for point in materialized.points] == [
        {"left": 1, "right": 3},
        {"left": 1, "right": 4},
        {"left": 2, "right": 3},
        {"left": 2, "right": 4},
    ]


def test_point_cloud_materialization_zips_columns_in_row_order() -> None:
    domain = PointDomain(
        axes=(
            _axis("x", (1, 2, 2)),
            _axis("y", (10, 20, 20)),
        ),
        layout="point_cloud",
    )

    verified = _verify(domain)
    materialized = materialize_point_domain(verified, ParameterRelationData())

    assert verified.cardinality == 3
    assert materialized.layout == "point_cloud"
    assert [point.row for point in materialized.points] == [
        {"x": 1, "y": 10},
        {"x": 2, "y": 20},
        {"x": 2, "y": 20},
    ]
    assert materialized.points[1].logical_id != materialized.points[2].logical_id


def test_point_cloud_rejects_coordinate_columns_with_different_lengths() -> None:
    domain = PointDomain(
        axes=(
            _axis("x", (1, 2)),
            _axis("y", (10,)),
        ),
        layout="point_cloud",
    )

    with pytest.raises(PointDomainVerificationError) as caught:
        _verify(domain)

    assert [issue.code for issue in caught.value.issues] == [
        "point_domain_point_cloud_length_mismatch"
    ]


def test_linear_axis_center_reads_dynamic_scalar_parameter() -> None:
    center = verified_scalar_expr(
        param("center", _TIME),
        bindings=ExpressionTypeBindings(parameters={"center": _TIME}),
        expected_type=_TIME,
    )
    verified = _verify(
        PointDomain(
            axes=(
                point_axis_linear(
                    "delay",
                    _TIME,
                    center,
                    _quantity(4.0),
                    3,
                ),
            )
        ),
        program_id="program",
    )

    materialized = materialize_point_domain(
        verified,
        ParameterRelationData(scalars={"center": _quantity(10.0)}),
    )

    [(path, source)] = iter_point_axis_linear(verified.axes)
    assert source.center is center
    assert path == ("axes", 0)
    assert [point.row for point in materialized.points] == [
        {"delay": _quantity(8.0)},
        {"delay": _quantity(10.0)},
        {"delay": _quantity(12.0)},
    ]


def test_linear_axis_normalizes_center_to_its_declared_value_type() -> None:
    gigahertz = Scalar(QuantityType(unit="GHz"))
    hertz = Scalar(QuantityType(unit="Hz"))
    materialized = _materialize(
        PointDomain(
            axes=(
                point_axis_linear(
                    "frequency",
                    gigahertz,
                    as_scalar_expr(
                        Quantity(value=5_000_000_000.0, unit="Hz"),
                        value_type=hertz,
                    ),
                    Quantity(value=1.0, unit="Hz"),
                    4,
                ),
            )
        )
    )

    assert [point.row["frequency"] for point in materialized.points] == [
        Quantity(value=4.9999999995, unit="GHz"),
        Quantity(value=4.999999999833333, unit="GHz"),
        Quantity(value=5.000000000166667, unit="GHz"),
        Quantity(value=5.0000000005, unit="GHz"),
    ]


def test_linear_axis_preserves_sub_picounit_steps_and_centered_endpoints() -> None:
    center = _quantity(1.0)
    span = _quantity(8e-13)

    values = [
        point_axis_linear_value(center, span, count=5, index=index).value
        for index in range(5)
    ]

    assert len(set(values)) == 5
    assert values[0] == center.value - span.value / 2
    assert values[2] == center.value
    assert values[-1] == center.value + span.value / 2


def test_dynamic_center_evaluation_errors_report_the_center_path() -> None:
    center = verified_scalar_expr(
        param("missing", _TIME),
        bindings=ExpressionTypeBindings(parameters={"missing": _TIME}),
        expected_type=_TIME,
    )
    verified = _verify(
        PointDomain(
            axes=(
                point_axis_linear(
                    "delay",
                    _TIME,
                    center,
                    _quantity(2.0),
                    3,
                ),
            )
        )
    )

    with pytest.raises(PointDomainEvaluationError) as caught:
        materialize_point_domain(verified, ParameterRelationData())

    assert caught.value.path == ("axes", 0, "source", "center")


def test_duplicate_columns_fail_during_typed_verification() -> None:
    domain = PointDomain(
        axes=(
            _axis("same", (1,)),
            _axis("same", (2,)),
        )
    )

    with pytest.raises(PointDomainVerificationError) as caught:
        _verify(domain)

    assert [issue.code for issue in caught.value.issues] == [
        "point_domain_duplicate_columns"
    ]
    assert caught.value.issues[0].path == ()


def test_linear_center_rejects_an_unresolved_input() -> None:
    center = verified_scalar_expr(
        input_ref("center", _TIME),
        bindings=ExpressionTypeBindings(inputs={"center": _TIME}),
        expected_type=_TIME,
    )

    with pytest.raises(PointDomainVerificationError) as caught:
        _verify(
            PointDomain(
                axes=(
                    point_axis_linear(
                        "delay",
                        _TIME,
                        center,
                        _quantity(2.0),
                        3,
                    ),
                )
            )
        )

    assert [issue.code for issue in caught.value.issues] == [
        "point_axis_center_open_input"
    ]
    assert caught.value.issues[0].path == ("axes", 0, "source", "center")


def test_linear_center_rejects_a_point_dependency() -> None:
    center = verified_scalar_expr(
        point_col("other", _TIME),
        bindings=ExpressionTypeBindings(
            point_row=RowType((TableColumn("other", _TIME),))
        ),
        expected_type=_TIME,
    )

    with pytest.raises(PointDomainVerificationError) as caught:
        _verify(
            PointDomain(
                axes=(
                    point_axis_linear(
                        "delay",
                        _TIME,
                        center,
                        _quantity(2.0),
                        3,
                    ),
                )
            )
        )

    assert [issue.code for issue in caught.value.issues] == [
        "point_axis_center_open_point"
    ]
    assert caught.value.issues[0].path == ("axes", 0, "source", "center")


def test_materialization_coerces_normalized_rows_before_assigning_ids() -> None:
    verified = _verify(_domain((1,)), program_id="program")
    materialized = materialize_point_domain(
        verified,
        ParameterRelationData(),
        row_normalizer=lambda _row: {"x": 2},
    )

    assert materialized.points[0].row == {"x": 2}
    assert materialized.points[0].logical_id == LogicalPointId(verified.id, 0)


def test_invalid_literal_or_normalized_cell_has_a_value_validation_error() -> None:
    invalid_literal = _verify(_domain(("not-an-integer",)))
    with pytest.raises(ValueValidationError):
        materialize_point_domain(invalid_literal, ParameterRelationData())

    verified = _verify(_domain((1,)))
    with pytest.raises(ValueValidationError):
        materialize_point_domain(
            verified,
            ParameterRelationData(),
            row_normalizer=lambda _row: {"x": "not-an-integer"},
        )


def test_entity_columns_are_derived_from_exact_point_schema() -> None:
    domain = PointDomain(
        axes=(
            _axis(
                "qubit",
                (EntityRef(id="q0", kind="qubit"),),
                value_type=_ENTITY,
            ),
        )
    )

    verified = _verify(domain)
    materialized = materialize_point_domain(verified, ParameterRelationData())

    assert verified.entity_columns == ("qubit",)
    assert [column.id for column in verified.coordinate_columns] == ["qubit"]
    assert materialized.points[0].row == {"qubit": EntityRef(id="q0", kind="qubit")}


def test_domain_namespace_and_ordinal_define_logical_identity() -> None:
    first = _materialize(_domain((7, 7), domain_id="first"), program_id="program")
    second = _materialize(_domain((7,), domain_id="second"), program_id="program")

    assert first.points[0].row == first.points[1].row
    assert first.points[0].logical_id != first.points[1].logical_id
    assert first.points[0].logical_id != second.points[0].logical_id
    assert first.points[0].logical_id == LogicalPointId(
        PointDomainId("program", "first"),
        0,
    )


def test_materialized_domain_accepts_nonzero_ordinal_coverage() -> None:
    verified = _verify(_domain((1,)), program_id="program")
    first = MaterializedPoint(LogicalPointId(verified.id, 7), {"x": 1})

    coverage = MaterializedPointDomain(
        verified.id,
        (first,),
    )
    assert coverage.points == (first,)


def test_row_normalizer_receives_detached_input_rows() -> None:
    seen: list[Mapping[str, object]] = []

    def normalize(row: Mapping[str, object]) -> Mapping[str, object]:
        seen.append(row)
        cast("dict[str, object]", row)["x"] = 9
        return row

    verified = _verify(_domain((1,)))
    materialized = materialize_point_domain(
        verified,
        ParameterRelationData(),
        row_normalizer=normalize,
    )

    assert seen == [{"x": 9}]
    assert materialized.points[0].row == {"x": 9}
    assert materialize_point_domain(
        verified,
        ParameterRelationData(),
    ).points[0].row == {"x": 1}
