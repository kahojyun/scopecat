from __future__ import annotations

from scopecat.compiler.relations.evaluation import (
    EvalContext,
    ParameterRelationData,
)
from scopecat.compiler.relations.evaluator import evaluate_scalar_expression
from scopecat.compiler.relations.model import (
    CaseBranch,
    CaseScalarExpr,
    input_ref,
    lit,
    param,
    point_col,
)
from scopecat.compiler.relations.specialization import (
    BindingTime,
    KnownScalar,
    ParameterCellBinding,
    ResidualScalar,
    specialize_scalar,
)


def _parameters() -> ParameterRelationData:
    return ParameterRelationData(
        scalars={"gain": 2},
        tables={
            "devices": [
                {"id": "q0", "frequency": 5.0},
                {"id": "q1", "frequency": 6.0},
            ]
        },
    )


def test_specialization_folds_request_and_configuration_values() -> None:
    expression = (input_ref("offset") + param("gain")) * 3

    result = specialize_scalar(
        expression,
        known=EvalContext(params=_parameters(), inputs={"offset": 4}),
    )

    assert result == KnownScalar(18)


def test_specialization_retains_point_expression_and_folds_static_branch() -> None:
    expression = (point_col("frequency") + param("gain")) * (1 + 2)

    result = specialize_scalar(expression, known=EvalContext(params=_parameters()))

    assert isinstance(result, ResidualScalar)
    assert result.binding_time is BindingTime.POINT
    assert {reference.id for reference in result.references} == {"frequency"}
    assert (
        evaluate_scalar_expression(
            result.expression,
            EvalContext(point_row={"frequency": 5.0}),
        )
        == 21.0
    )


def test_specialization_folds_closed_parameter_lookup() -> None:
    expression = param("devices", key={"id": "q1"}, column="frequency") + 1

    result = specialize_scalar(expression, known=EvalContext(params=_parameters()))

    assert result == KnownScalar(7.0)


def test_specialization_retains_lookup_with_point_varying_key() -> None:
    expression = param(
        "devices",
        key={"id": point_col("device")},
        column="frequency",
    )

    result = specialize_scalar(expression, known=EvalContext(params=_parameters()))

    assert isinstance(result, ResidualScalar)
    assert result.binding_time is BindingTime.POINT
    assert {reference.id for reference in result.references} == {
        "devices",
        "device",
    }
    assert (
        evaluate_scalar_expression(
            result.expression,
            EvalContext(params=_parameters(), point_row={"device": "q0"}),
        )
        == 5.0
    )


def test_specialization_substitutes_scanned_parameter_cell() -> None:
    binding = ParameterCellBinding(
        table_id="devices",
        key=(("id", "q0"),),
        column_id="frequency",
        replacement=point_col("frequency"),
    )
    expression = param(
        "devices",
        key={"id": "q0"},
        column="frequency",
    )

    result = specialize_scalar(
        expression,
        known=EvalContext(params=_parameters()),
        parameter_cells=(binding,),
    )

    assert isinstance(result, ResidualScalar)
    assert result.expression == point_col("frequency")
    assert result.binding_time is BindingTime.POINT


def test_specialization_prunes_known_case_prefix() -> None:
    expression = CaseScalarExpr(
        cases=[
            CaseBranch(condition=lit(False), value=lit(0)),
            CaseBranch(
                condition=point_col("enabled").eq(True),
                value=param("gain"),
            ),
        ],
        fallback=input_ref("fallback"),
    )

    result = specialize_scalar(
        expression,
        known=EvalContext(params=_parameters(), inputs={"fallback": 9}),
    )

    assert isinstance(result, ResidualScalar)
    assert isinstance(result.expression, CaseScalarExpr)
    assert len(result.expression.cases) == 1
    assert result.expression.fallback == lit(9)


def test_specialized_residual_is_equivalent_for_remaining_point_bindings() -> None:
    expression = (point_col("value") * param("gain")) + input_ref("offset")
    known = EvalContext(params=_parameters(), inputs={"offset": 1})
    result = specialize_scalar(expression, known=known)

    assert isinstance(result, ResidualScalar)
    for point_value in (-2, 0, 3):
        full_context = EvalContext(
            params=_parameters(),
            inputs={"offset": 1},
            point_row={"value": point_value},
        )
        residual_context = EvalContext(point_row={"value": point_value})
        assert evaluate_scalar_expression(
            expression,
            full_context,
        ) == evaluate_scalar_expression(result.expression, residual_context)
