from __future__ import annotations

import pytest

from scopecat.compiler.relations.context import (
    EvalContext,
    ParameterRelationData,
)
from scopecat.compiler.relations.evaluation import evaluate_table_value
from scopecat.compiler.relations.evaluator import evaluate_scalar_expression
from scopecat.compiler.relations.verification import RelationTypeBindings, RowType
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.quantity import Quantity as QuantityValue
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_data import CellValue, Row
from scopecat.kernel.value_types import (
    Entity,
    Int,
    Quantity,
    Scalar,
    String,
    Table,
    TableColumn,
)
from scopecat.kernel.value_validation import ValueValidationError
from scopecat.program.expressions import (
    ComputeResultScalarExpr,
    ModuleExportScalarExpr,
    ParameterLookupUse,
    input_ref,
    param,
    parameter_lookup,
    point_col,
)
from scopecat.program.identities import InvocationKey
from scopecat.program.table_values import ParameterTableSource
from scopecat.program.value_graph import ValueId
from tests.testkit.relation_plans import evaluate_scalar

_INT = Scalar(Int())
_FREQUENCY = Scalar(Quantity(unit="GHz"))
_STRING = Scalar(String())


def _int_row(*column_ids: str) -> RowType:
    return RowType(tuple(TableColumn(column_id, _INT) for column_id in column_ids))


def test_parameter_data_owns_its_containers_and_returns_detached_values() -> None:
    source_scalars: dict[str, CellValue] = {"gain": 1}
    source_rows: list[Row] = [{"id": "r0", "value": 4}]
    parameters = ParameterRelationData(
        scalars=source_scalars,
        tables={"calibrations": source_rows},
    )

    source_scalars["gain"] = 10
    source_rows[0]["value"] = 40
    table_rows = parameters.table_rows("calibrations")
    table_rows[0]["value"] = 50

    assert parameters.scalar("gain") == 1
    assert parameters.table_rows("calibrations") == [{"id": "r0", "value": 4}]


def test_lexical_point_binding_replaces_a_cell_without_mutating_base_data() -> None:
    base = ParameterRelationData(tables={"calibrations": [{"id": "r0", "value": 1}]})
    point_parameters = base.with_table_cell(
        "calibrations",
        row_index=0,
        column_id="value",
        value=2,
    )

    assert point_parameters.table_rows("calibrations") == [{"id": "r0", "value": 2}]
    assert base.table_rows("calibrations") == [{"id": "r0", "value": 1}]


def test_evaluation_validates_only_used_typed_imports() -> None:
    bindings = RelationTypeBindings(inputs={"used": _INT, "unused": _INT})
    valid = EvalContext(inputs={"used": 1, "unused": "not-an-int"})

    assert (
        evaluate_scalar(
            input_ref("used", _INT),
            valid,
            bindings=bindings,
        )
        == 1
    )

    invalid = EvalContext(inputs={"used": "not-an-int", "unused": 1})
    with pytest.raises(ValueValidationError, match=r"inputs\.used: expected int"):
        evaluate_scalar(
            input_ref("used", _INT),
            invalid,
            bindings=bindings,
        )


def test_evaluation_validates_used_parameter_contracts() -> None:
    ctx = EvalContext(params=ParameterRelationData(scalars={"gain": "not-an-int"}))

    with pytest.raises(ValueValidationError, match=r"parameters\.gain: expected int"):
        evaluate_scalar(
            param("gain", _INT),
            ctx,
            bindings=RelationTypeBindings(parameters={"gain": _INT}),
        )


def test_evaluation_normalizes_multiple_lookup_projections_cumulatively() -> None:
    signatures = tuple(
        ParameterLookupUse(
            table_id="devices",
            key_input_types=(("id", _STRING),),
            literal_key_columns=frozenset({"id"}),
            column_id=column_id,
            result_type=_FREQUENCY,
        )
        for column_id in ("first", "second")
    )
    expression = parameter_lookup(
        signatures[0],
        key={"id": "q0"},
    ) + parameter_lookup(
        signatures[1],
        key={"id": "q0"},
    )
    context = EvalContext(
        params=ParameterRelationData(
            tables={
                "devices": [
                    {
                        "id": "q0",
                        "first": {"value": 5_000.0, "unit": "MHz"},
                        "second": {"value": 6.0, "unit": "GHz"},
                    }
                ]
            }
        )
    )

    assert evaluate_scalar(
        expression,
        context,
        bindings=RelationTypeBindings(),
    ) == QuantityValue(value=11.0, unit="GHz")


def test_evaluation_rejects_invalid_lookup_projection_without_config_binding() -> None:
    use = ParameterLookupUse(
        table_id="devices",
        key_input_types=(("id", _STRING),),
        literal_key_columns=frozenset({"id"}),
        column_id="frequency",
        result_type=_FREQUENCY,
    )
    context = EvalContext(
        params=ParameterRelationData(
            tables={"devices": [{"id": "q0", "frequency": "not-a-quantity"}]}
        )
    )

    with pytest.raises(
        ValueValidationError,
        match=r"parameters\.devices\[0\]\.frequency: expected quantity",
    ):
        evaluate_scalar(
            parameter_lookup(use, key={"id": "q0"}),
            context,
            bindings=RelationTypeBindings(),
        )


def test_evaluation_normalizes_a_used_parameter_table() -> None:
    table_type = Table(columns=(TableColumn("frequency", _FREQUENCY),))
    parameters = ParameterRelationData(
        tables={
            "devices": [
                {"frequency": {"value": 5_000.0, "unit": "MHz"}},
            ]
        }
    )

    assert evaluate_table_value(
        ParameterTableSource("devices"),
        table_type,
        EvalContext(params=parameters),
    ) == [{"frequency": QuantityValue(value=5.0, unit="GHz")}]


@pytest.mark.parametrize(
    ("value_type", "raw", "expected"),
    [
        (
            Scalar(Entity(entity_kind="qubit")),
            {"id": "q0"},
            EntityRef(id="q0", kind="qubit"),
        ),
        (
            Scalar(Quantity(dimension="frequency", unit="GHz")),
            {"value": 5.0, "unit": "GHz"},
            QuantityValue(value=5.0, unit="GHz"),
        ),
    ],
)
def test_evaluation_normalizes_used_context_values(
    value_type: Scalar,
    raw: object,
    expected: object,
) -> None:
    assert (
        evaluate_scalar(
            input_ref("value", value_type),
            EvalContext(inputs={"value": raw}),
            bindings=RelationTypeBindings(inputs={"value": value_type}),
        )
        == expected
    )


def test_evaluation_retains_a_narrow_binding_without_retyping_the_ast() -> None:
    generic = Scalar(Entity())
    qubit = Scalar(Entity(entity_kind="qubit"))
    expression = input_ref("value", generic)

    result = evaluate_scalar(
        expression,
        EvalContext(inputs={"value": "q0"}),
        bindings=RelationTypeBindings(inputs={"value": qubit}),
        expected_type=qubit,
    )

    assert expression.value_type == generic
    assert result == EntityRef(id="q0", kind="qubit")


def test_evaluation_applies_the_verified_consumer_type_without_retyping() -> None:
    generic_frequency = Scalar(Quantity(dimension="frequency"))
    ghz_frequency = Scalar(Quantity(dimension="frequency", unit="GHz"))
    expression = point_col("frequency", generic_frequency)

    result = evaluate_scalar(
        expression,
        EvalContext(
            point_row={
                "frequency": QuantityValue(value=5_000.0, unit="MHz"),
            }
        ),
        bindings=RelationTypeBindings(
            point_row=RowType((TableColumn("frequency", generic_frequency),))
        ),
        expected_type=ghz_frequency,
    )

    assert expression.value_type == generic_frequency
    assert result == QuantityValue(value=5.0, unit="GHz")


def test_evaluation_normalizes_only_referenced_point_columns() -> None:
    row: Row = {
        "frequency": {"value": 5_000.0, "unit": "MHz"},
        "unused": "not-an-int",
    }

    assert evaluate_scalar(
        point_col("frequency", _FREQUENCY),
        EvalContext(point_row=row),
        bindings=RelationTypeBindings(
            point_row=RowType(
                (
                    TableColumn("frequency", _FREQUENCY),
                    TableColumn("unused", _INT),
                )
            )
        ),
    ) == QuantityValue(value=5.0, unit="GHz")


def test_evaluation_validates_used_point_values() -> None:
    row: Row = {"value": "not-an-int"}

    with pytest.raises(ValueValidationError, match="expected int"):
        evaluate_scalar(
            point_col("value", _INT),
            EvalContext(point_row=row),
            bindings=RelationTypeBindings(point_row=_int_row("value")),
        )


def test_pure_evaluator_rejects_compute_results() -> None:
    expression = ComputeResultScalarExpr(
        value_id=ValueId(SymbolId(local_id="computed")),
        value_type=_INT,
    )

    with pytest.raises(TypeError, match="cannot be evaluated as pure"):
        evaluate_scalar_expression(expression, EvalContext())


def test_pure_evaluator_rejects_unresolved_module_exports() -> None:
    expression = ModuleExportScalarExpr(
        invocation_key=InvocationKey.fresh(),
        export_id="value",
        value_type=_INT,
    )

    with pytest.raises(ValueError, match="unresolved module exports"):
        evaluate_scalar_expression(expression, EvalContext())
