from __future__ import annotations

import pytest

from scopecat.compiler.relations.context import (
    EvalContext,
    ParameterRelationData,
)
from scopecat.compiler.relations.verification import RelationTypeBindings, RowType
from scopecat.graph.relations.model import (
    CellValue,
    ParameterLookupUse,
    Row,
    input_ref,
    input_table,
    param,
    parameter_lookup,
    point_col,
    table,
)
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.quantity import Quantity as QuantityValue
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
from tests.testkit.relation_plans import evaluate_relation, evaluate_scalar

_INT = Scalar(Int())
_FREQUENCY = Scalar(Quantity(unit="GHz"))
_STRING = Scalar(String())


def _int_row(*column_ids: str) -> RowType:
    return RowType(tuple(TableColumn(column_id, _INT) for column_id in column_ids))


def test_parameter_data_owns_its_containers_and_returns_detached_values() -> None:
    source_scalars: dict[str, CellValue] = {"gain": 1}
    source_series: list[CellValue] = [2, 3]
    source_rows: list[Row] = [{"id": "r0", "value": 4}]
    parameters = ParameterRelationData(
        scalars=source_scalars,
        series={"offsets": source_series},
        tables={"calibrations": source_rows},
    )

    source_scalars["gain"] = 10
    source_series[0] = 20
    source_rows[0]["value"] = 40
    series_values = parameters.series_values("offsets")
    table_rows = parameters.table_rows("calibrations")
    series_values[0] = 30
    table_rows[0]["value"] = 50

    assert parameters.scalar("gain") == 1
    assert parameters.series_values("offsets") == [2, 3]
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
            input_ref("used"),
            valid,
            bindings=bindings,
        )
        == 1
    )

    invalid = EvalContext(inputs={"used": "not-an-int", "unused": 1})
    with pytest.raises(ValueValidationError, match=r"inputs\.used: expected int"):
        evaluate_scalar(
            input_ref("used"),
            invalid,
            bindings=bindings,
        )


def test_evaluation_validates_used_parameter_contracts() -> None:
    ctx = EvalContext(params=ParameterRelationData(scalars={"gain": "not-an-int"}))

    with pytest.raises(ValueValidationError, match=r"parameters\.gain: expected int"):
        evaluate_scalar(
            param("gain"),
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


def test_evaluation_rejects_invalid_lookup_projection_without_linking() -> None:
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
    table_type = Table(
        columns=(TableColumn("frequency", _FREQUENCY),),
        min_rows=1,
        max_rows=1,
    )
    parameters = ParameterRelationData(
        tables={
            "devices": [
                {"frequency": {"value": 5_000.0, "unit": "MHz"}},
            ]
        }
    )

    assert evaluate_relation(
        table("devices"),
        EvalContext(params=parameters),
        bindings=RelationTypeBindings(parameters={"devices": table_type}),
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
            input_ref("value"),
            EvalContext(inputs={"value": raw}),
            bindings=RelationTypeBindings(inputs={"value": value_type}),
        )
        == expected
    )


def test_evaluation_rejects_invalid_open_input_carrier() -> None:
    open_rows = Table(
        columns=(),
        min_rows=1,
        max_rows=1,
        allow_extra_columns=True,
    )

    with pytest.raises(ValueValidationError, match="unsupported table runtime cell"):
        evaluate_relation(
            input_table("rows"),
            EvalContext(inputs={"rows": [{"extra": object()}]}),
            bindings=RelationTypeBindings(inputs={"rows": open_rows}),
        )


def test_evaluation_validates_used_point_values() -> None:
    row: Row = {"value": "not-an-int"}

    with pytest.raises(ValueValidationError, match="expected int"):
        evaluate_scalar(
            point_col("value"),
            EvalContext(point_row=row),
            bindings=RelationTypeBindings(point_row=_int_row("value")),
        )
