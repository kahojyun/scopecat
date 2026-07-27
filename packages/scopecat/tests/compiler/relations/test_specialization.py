from __future__ import annotations

from scopecat.compiler.relations.context import (
    EvalContext,
    ParameterRelationData,
)
from scopecat.compiler.relations.evaluator import evaluate_scalar_expression
from scopecat.compiler.relations.specialization import (
    KnownScalar,
    ParameterCellBinding,
    ResidualScalar,
    specialize_scalar,
)
from scopecat.graph.relations.model import (
    ParameterLookupUse,
    input_ref,
    param,
    parameter_lookup,
    point_col,
)
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.value_types import Entity, Float, Scalar, String

_DEVICE_FREQUENCY_LOOKUP = ParameterLookupUse(
    table_id="devices",
    key_input_types=(("id", Scalar(String())),),
    literal_key_columns=frozenset(),
    column_id="frequency",
    result_type=Scalar(Float()),
)
_ENTITY_DEVICE_FREQUENCY_LOOKUP = ParameterLookupUse(
    table_id="devices",
    key_input_types=(("id", Scalar(Entity(entity_kind="qubit"))),),
    literal_key_columns=frozenset(),
    column_id="frequency",
    result_type=Scalar(Float()),
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
    assert (
        evaluate_scalar_expression(
            result.expression,
            EvalContext(point_row={"frequency": 5.0}),
        )
        == 21.0
    )


def test_specialization_folds_closed_parameter_lookup() -> None:
    expression = parameter_lookup(_DEVICE_FREQUENCY_LOOKUP, key={"id": "q1"}) + 1

    result = specialize_scalar(expression, known=EvalContext(params=_parameters()))

    assert result == KnownScalar(7.0)


def test_specialization_retains_lookup_with_point_varying_key() -> None:
    expression = parameter_lookup(
        _DEVICE_FREQUENCY_LOOKUP,
        key={"id": point_col("device")},
    )

    result = specialize_scalar(expression, known=EvalContext(params=_parameters()))

    assert isinstance(result, ResidualScalar)
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
    expression = parameter_lookup(
        _DEVICE_FREQUENCY_LOOKUP,
        key={"id": "q0"},
    )

    result = specialize_scalar(
        expression,
        known=EvalContext(params=_parameters()),
        parameter_cells=(binding,),
    )

    assert isinstance(result, ResidualScalar)
    assert result.expression == point_col("frequency")


def test_specialization_matches_entity_overlay_to_literal_id() -> None:
    binding = ParameterCellBinding(
        table_id="devices",
        key=(("id", EntityRef(id="q0", kind="qubit")),),
        column_id="frequency",
        replacement=point_col("frequency"),
    )

    result = specialize_scalar(
        parameter_lookup(_ENTITY_DEVICE_FREQUENCY_LOOKUP, key={"id": "q0"}),
        known=EvalContext(params=_parameters()),
        parameter_cells=(binding,),
    )

    assert isinstance(result, ResidualScalar)
    assert result.expression == point_col("frequency")


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
