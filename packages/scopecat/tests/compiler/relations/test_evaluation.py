from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from scopecat.compiler.relations.analysis import (
    RelationPlanScopeError,
    verify_plan_scopes,
)
from scopecat.compiler.relations.evaluation import (
    EvalContext,
    ParameterRelationData,
)
from scopecat.compiler.relations.model import (
    CellValue,
    ParameterLookupUse,
    Row,
    RowScopeId,
    col,
    input_ref,
    input_table,
    literal_rows,
    param,
    parameter_lookup,
    point_col,
    table,
)
from scopecat.compiler.relations.verification import RelationTypeBindings, RowType
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import (
    Bool,
    Entity,
    Int,
    Quantity,
    Scalar,
    String,
    Table,
    TableColumn,
)
from scopecat.kernel.value_validation import ValueValidationError
from scopecat.records.entity import EntityRef
from scopecat.records.parameter import Quantity as QuantityValue
from tests.testkit.relation_plans import evaluate_relation, evaluate_scalar

_SMALL_INT = st.integers(min_value=-2, max_value=2)
_INT = Scalar(Int())
_FREQUENCY = Scalar(Quantity(unit="GHz"))
_STRING = Scalar(String())
_NULLABLE_BOOL = Scalar(Bool(), nullable=True)


def _row_scope(local_id: str) -> RowScopeId:
    return RowScopeId(SymbolId(local_id=local_id))


def _int_row(*column_ids: str) -> RowType:
    return RowType(tuple(TableColumn(column_id, _INT) for column_id in column_ids))


@settings(max_examples=50)
@given(
    cells=st.lists(
        st.tuples(
            _SMALL_INT,
            st.one_of(st.none(), st.booleans()),
        ),
        max_size=5,
    ),
    offset=_SMALL_INT,
)
def test_generated_unary_pipeline_preserves_relative_row_order(
    cells: list[tuple[int, bool | None]],
    offset: int,
) -> None:
    filter_scope = _row_scope("filter-row")
    derived_scope = _row_scope("derived-row")
    rows = [
        {"token": token, "value": value, "keep": keep}
        for token, (value, keep) in enumerate(cells)
    ]
    plan = (
        input_table("rows")
        .filter(
            col("keep", row_scope_id=filter_scope).eq(True),
            row_scope_id=filter_scope,
        )
        .with_columns(
            row_scope_id=derived_scope,
            derived=col("value", row_scope_id=derived_scope) + offset,
        )
        .select("token", "derived")
    )

    actual = evaluate_relation(
        plan,
        EvalContext(inputs={"rows": rows}),
        bindings=RelationTypeBindings(
            inputs={
                "rows": Table(
                    (
                        TableColumn("token", _INT),
                        TableColumn("value", _INT),
                        TableColumn("keep", _NULLABLE_BOOL),
                    )
                )
            }
        ),
    )
    expected = [
        {"token": token, "derived": value + offset}
        for token, (value, keep) in enumerate(cells)
        if keep is True
    ]

    assert actual == expected
    assert all(tuple(row) == ("token", "derived") for row in actual)


@settings(max_examples=50)
@given(local_value=_SMALL_INT, point_value=_SMALL_INT)
def test_generated_point_and_local_columns_do_not_capture_same_named_values(
    local_value: int,
    point_value: int,
) -> None:
    local_scope = _row_scope("local-row")
    plan = literal_rows([{"shared": local_value}]).with_columns(
        row_scope_id=local_scope,
        local_copy=col("shared", row_scope_id=local_scope),
        point_copy=point_col("shared"),
    )

    assert evaluate_relation(
        plan,
        EvalContext(point_row={"shared": point_value}),
        bindings=RelationTypeBindings(point_row=_int_row("shared")),
    ) == [
        {
            "shared": local_value,
            "local_copy": local_value,
            "point_copy": point_value,
        }
    ]


def test_scope_verifier_rejects_value_captured_from_foreign_row_scope() -> None:
    foreign_scope = _row_scope("foreign-row")
    active_scope = _row_scope("active-row")
    captured = col("value", row_scope_id=foreign_scope)
    plan = literal_rows([{"value": 1}]).with_columns(
        row_scope_id=active_scope,
        captured=captured,
    )

    with pytest.raises(RelationPlanScopeError) as error:
        verify_plan_scopes(plan)

    assert error.value.reference.id == "value"
    assert error.value.reference.row_scope_id == foreign_scope


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


@pytest.mark.parametrize("role", ["point", "argument"])
def test_evaluation_validates_used_row_roles(role: str) -> None:
    row_scope_id = _row_scope("external")
    row: Row = {"value": "not-an-int"}
    if role == "point":
        expression = point_col("value")
        bindings = RelationTypeBindings(point_row=_int_row("value"))
        ctx = EvalContext(point_row=row)
    else:
        expression = col("value", row_scope_id=row_scope_id)
        bindings = RelationTypeBindings(row_arguments={row_scope_id: _int_row("value")})
        ctx = EvalContext(row_scopes={row_scope_id: row})

    with pytest.raises(ValueValidationError, match="expected int"):
        evaluate_scalar(
            expression,
            ctx,
            bindings=bindings,
        )
