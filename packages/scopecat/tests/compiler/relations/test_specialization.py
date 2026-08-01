from __future__ import annotations

import pytest

from scopecat.compiler.relations.context import (
    EvalContext,
    ParameterRelationData,
)
from scopecat.compiler.relations.evaluator import evaluate_scalar_expression
from scopecat.compiler.relations.specialization import (
    ParameterCellBinding,
    specialize_scalar_expression,
)
from scopecat.compiler.relations.verification import ExpressionVerificationError
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.value_types import Entity, Float, Int, Scalar, String
from scopecat.program.expressions import (
    LiteralScalarExpr,
    ParameterLookupUse,
    input_ref,
    lit,
    param,
    parameter_lookup,
    point_col,
)

_FLOAT = Scalar(Float())
_STRING = Scalar(String())
_QUBIT = Scalar(Entity(entity_kind="qubit"))
_DEVICE_FREQUENCY_LOOKUP = ParameterLookupUse(
    table_id="devices",
    key_input_types=(("id", _STRING),),
    literal_key_columns=frozenset(),
    column_id="frequency",
    result_type=_FLOAT,
)
_ENTITY_DEVICE_FREQUENCY_LOOKUP = ParameterLookupUse(
    table_id="devices",
    key_input_types=(("id", _QUBIT),),
    literal_key_columns=frozenset(),
    column_id="frequency",
    result_type=_FLOAT,
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
    expression = (input_ref("offset", _FLOAT) + param("gain", _FLOAT)) * 3

    result = specialize_scalar_expression(
        expression,
        known=EvalContext(params=_parameters(), inputs={"offset": 4}),
    )

    assert result == lit(18, _FLOAT)


def test_specialization_preserves_an_import_with_an_invalid_known_value() -> None:
    integer = Scalar(Int())
    expression = param("gain", integer)

    result = specialize_scalar_expression(
        expression,
        known=EvalContext(params=ParameterRelationData(scalars={"gain": "not-an-int"})),
    )

    assert result is expression


def test_specialization_rejects_a_statically_known_zero_denominator() -> None:
    integer = Scalar(Int())

    with pytest.raises(ExpressionVerificationError) as caught:
        specialize_scalar_expression(
            lit(1, integer) / param("denominator", integer),
            known=EvalContext(params=ParameterRelationData(scalars={"denominator": 0})),
        )

    assert caught.value.code == "division_by_zero"
    assert caught.value.path == ("right",)


def test_specialization_rejects_a_non_finite_known_result() -> None:
    expression = lit(1e308, _FLOAT) * param("scale", _FLOAT)

    with pytest.raises(ExpressionVerificationError) as caught:
        specialize_scalar_expression(
            expression,
            known=EvalContext(params=ParameterRelationData(scalars={"scale": 1e308})),
        )

    assert caught.value.code == "scalar_evaluation_failed"
    assert "non-finite result" in caught.value.reason


def test_specialization_rejects_a_known_lookup_without_one_matching_row() -> None:
    expression = parameter_lookup(
        _DEVICE_FREQUENCY_LOOKUP,
        key={"id": "missing"},
    )

    with pytest.raises(ExpressionVerificationError) as caught:
        specialize_scalar_expression(
            expression,
            known=EvalContext(params=_parameters()),
        )

    assert caught.value.code == "parameter_lookup_failed"
    assert "matched 0 rows" in caught.value.reason


def test_specialization_retains_point_expression_and_folds_static_branch() -> None:
    expression = (point_col("frequency", _FLOAT) + param("gain", _FLOAT)) * (1 + 2)

    result = specialize_scalar_expression(
        expression,
        known=EvalContext(params=_parameters()),
    )

    assert (
        evaluate_scalar_expression(
            result,
            EvalContext(point_row={"frequency": 5.0}),
        )
        == 21.0
    )


def test_specialization_folds_closed_parameter_lookup() -> None:
    expression = parameter_lookup(_DEVICE_FREQUENCY_LOOKUP, key={"id": "q1"}) + 1

    result = specialize_scalar_expression(
        expression,
        known=EvalContext(params=_parameters()),
    )

    assert result == lit(7.0, _FLOAT)


def test_specialization_retains_lookup_with_point_varying_key() -> None:
    expression = parameter_lookup(
        _DEVICE_FREQUENCY_LOOKUP,
        key={"id": point_col("device", _STRING)},
    )

    result = specialize_scalar_expression(
        expression,
        known=EvalContext(params=_parameters()),
    )

    assert (
        evaluate_scalar_expression(
            result,
            EvalContext(params=_parameters(), point_row={"device": "q0"}),
        )
        == 5.0
    )


def test_specialization_substitutes_scanned_parameter_cell() -> None:
    binding = ParameterCellBinding(
        table_id="devices",
        key=(("id", "q0"),),
        column_id="frequency",
        replacement=point_col("frequency", _FLOAT),
    )
    expression = parameter_lookup(
        _DEVICE_FREQUENCY_LOOKUP,
        key={"id": "q0"},
    )

    result = specialize_scalar_expression(
        expression,
        known=EvalContext(params=_parameters()),
        parameter_cells=(binding,),
    )

    assert result == point_col("frequency", _FLOAT)


def test_specialization_matches_entity_overlay_to_literal_id() -> None:
    binding = ParameterCellBinding(
        table_id="devices",
        key=(("id", EntityRef(id="q0", kind="qubit")),),
        column_id="frequency",
        replacement=point_col("frequency", _FLOAT),
    )

    result = specialize_scalar_expression(
        parameter_lookup(_ENTITY_DEVICE_FREQUENCY_LOOKUP, key={"id": "q0"}),
        known=EvalContext(params=_parameters()),
        parameter_cells=(binding,),
    )

    assert result == point_col("frequency", _FLOAT)


def test_specialized_residual_is_equivalent_for_remaining_point_bindings() -> None:
    expression = (point_col("value", _FLOAT) * param("gain", _FLOAT)) + input_ref(
        "offset",
        _FLOAT,
    )
    known = EvalContext(params=_parameters(), inputs={"offset": 1})
    result = specialize_scalar_expression(expression, known=known)

    assert not isinstance(result, LiteralScalarExpr)
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
        ) == evaluate_scalar_expression(result, residual_context)
