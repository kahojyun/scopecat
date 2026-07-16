from __future__ import annotations

from itertools import product

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from scopecat.compiler.relations.analysis import (
    RelationPlanScopeError,
    verify_plan_scopes,
)
from scopecat.compiler.relations.evaluation import (
    ParameterRelationData,
)
from scopecat.compiler.relations.model import (
    CellValue,
    Row,
    RowScopeId,
    col,
    grid,
    input_ref,
    input_series,
    input_table,
    literal_rows,
    outer,
    param,
    point_col,
)
from scopecat.compiler.relations.verification import RelationTypeBindings, RowType
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import (
    Bool,
    Entity,
    Int,
    Quantity,
    Scalar,
    Series,
    Table,
    TableColumn,
)
from scopecat.kernel.value_validation import ValueValidationError
from scopecat.records.entity import EntityRef
from scopecat.records.parameter import Quantity as QuantityValue
from tests.testkit.relation_plans import evaluate_relation, evaluate_scalar

_SMALL_INT = st.integers(min_value=-2, max_value=2)
_SMALL_AXIS = st.lists(_SMALL_INT, max_size=3)
_SMALL_ROWS = st.lists(_SMALL_INT, max_size=4)
_INT = Scalar(Int())
_NULLABLE_BOOL = Scalar(Bool(), nullable=True)


def _row_scope(local_id: str) -> RowScopeId:
    return RowScopeId(SymbolId(local_id=local_id))


def _int_row(*column_ids: str) -> RowType:
    return RowType(tuple(TableColumn(column_id, _INT) for column_id in column_ids))


def _int_table(*column_ids: str) -> Table:
    return Table(tuple(TableColumn(column_id, _INT) for column_id in column_ids))


@settings(max_examples=50)
@given(
    axis_order=st.sampled_from((("axis_a", "axis_b"), ("axis_b", "axis_a"))),
    axis_a=_SMALL_AXIS,
    axis_b=_SMALL_AXIS,
)
def test_generated_grid_respects_axis_declaration_order(
    axis_order: tuple[str, str],
    axis_a: list[int],
    axis_b: list[int],
) -> None:
    values_by_axis = {"axis_a": axis_a, "axis_b": axis_b}
    plan = grid(**{axis: input_series(axis) for axis in axis_order})

    actual = evaluate_relation(
        plan,
        inputs=values_by_axis,
        bindings=RelationTypeBindings(
            inputs={axis: Series(_INT) for axis in axis_order}
        ),
    )
    expected = [
        dict(zip(axis_order, combination, strict=True))
        for combination in product(*(values_by_axis[axis] for axis in axis_order))
    ]

    assert actual == expected
    assert all(tuple(row) == axis_order for row in actual)


@settings(max_examples=50)
@given(left_values=_SMALL_ROWS, right_values=_SMALL_ROWS)
def test_generated_cross_is_left_major_and_preserves_duplicates(
    left_values: list[int],
    right_values: list[int],
) -> None:
    plan = input_table("left_rows").cross(input_table("right_rows"))

    assert evaluate_relation(
        plan,
        inputs={
            "left_rows": [{"left": value} for value in left_values],
            "right_rows": [{"right": value} for value in right_values],
        },
        bindings=RelationTypeBindings(
            inputs={
                "left_rows": _int_table("left"),
                "right_rows": _int_table("right"),
            }
        ),
    ) == [
        {"left": left, "right": right} for left in left_values for right in right_values
    ]


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
    limit=st.integers(min_value=0, max_value=6),
)
def test_generated_unary_pipeline_preserves_relative_row_order(
    cells: list[tuple[int, bool | None]],
    offset: int,
    limit: int,
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
        .limit(limit)
    )

    actual = evaluate_relation(
        plan,
        inputs={"rows": rows},
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
    ][:limit]

    assert actual == expected
    assert all(tuple(row) == ("token", "derived") for row in actual)


@settings(max_examples=50)
@given(keys=st.lists(_SMALL_INT, max_size=6))
def test_generated_sort_is_stable_for_equal_keys(keys: list[int]) -> None:
    rows = [{"key": key, "token": token} for token, key in enumerate(keys)]
    plan = input_table("rows").sort("key")

    assert evaluate_relation(
        plan,
        inputs={"rows": rows},
        bindings=RelationTypeBindings(inputs={"rows": _int_table("key", "token")}),
    ) == sorted(
        rows,
        key=lambda row: row["key"],
    )


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
        point_row={"shared": point_value},
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


def test_scope_verifier_rejects_outer_column_without_an_outer_binding() -> None:
    with pytest.raises(RelationPlanScopeError) as error:
        verify_plan_scopes(outer("value"))

    assert error.value.reference.id == "value"
    assert error.value.reference.kind.value == "outer_column"


def test_empty_current_row_is_present_even_when_it_has_no_columns() -> None:
    with pytest.raises(ValueValidationError, match="missing required columns: missing"):
        evaluate_relation(
            grid(copied=col("missing")),
            row={},
            bindings=RelationTypeBindings(current_row=_int_row("missing")),
        )


@settings(max_examples=50)
@given(
    left_values=st.lists(_SMALL_INT, min_size=1, max_size=4),
    ambient_value=_SMALL_INT,
)
def test_generated_lateral_cross_is_explicitly_correlated(
    left_values: list[int],
    ambient_value: int,
) -> None:
    left = literal_rows([{"left": value} for value in left_values])
    cross = left.cross(grid(observed=col("ambient")))
    lateral = left.lateral_cross(grid(observed=col("left")))
    point_cross = left.point_cross(grid(observed=point_col("left")))

    assert evaluate_relation(
        cross,
        row={"ambient": ambient_value},
        bindings=RelationTypeBindings(current_row=_int_row("ambient")),
    ) == [{"left": value, "observed": ambient_value} for value in left_values]
    assert evaluate_relation(
        lateral,
        row={"ambient": ambient_value},
        bindings=RelationTypeBindings(current_row=_int_row("ambient")),
    ) == [{"left": value, "observed": value} for value in left_values]
    assert evaluate_relation(
        point_cross,
    ) == [{"left": value, "observed": value} for value in left_values]

    with pytest.raises(ValueValidationError, match="missing required columns: left"):
        evaluate_relation(
            left.cross(grid(observed=col("left"))),
            row={"ambient": ambient_value},
            bindings=RelationTypeBindings(current_row=_int_row("ambient", "left")),
        )


@settings(max_examples=50)
@given(local_value=_SMALL_INT, point_value=_SMALL_INT)
def test_generated_lateral_cross_never_rebinds_the_point_row(
    local_value: int,
    point_value: int,
) -> None:
    plan = literal_rows([{"shared": local_value}]).lateral_cross(
        grid(observed=point_col("shared"))
    )

    assert evaluate_relation(
        plan,
        point_row={"shared": point_value},
        bindings=RelationTypeBindings(point_row=_int_row("shared")),
    ) == [{"shared": local_value, "observed": point_value}]


def test_lateral_cross_exposes_left_row_as_nested_outer_scope() -> None:
    plan = literal_rows([{"left": 1}, {"left": 2}]).lateral_cross(
        literal_rows([{"right": 2}, {"right": 1}]).filter(
            col("right").eq(outer("left"))
        )
    )

    assert evaluate_relation(plan) == [
        {"left": 1, "right": 1},
        {"left": 2, "right": 2},
    ]


@settings(max_examples=50)
@given(values=_SMALL_ROWS)
def test_generated_point_cross_is_associative(values: list[int]) -> None:
    first = input_table("first_rows")
    second = grid(second=point_col("first") + 1)
    third = grid(third=point_col("second") + 1)

    left_associated = first.point_cross(second).point_cross(third)
    right_associated = first.point_cross(second.point_cross(third))

    assert evaluate_relation(
        left_associated,
        inputs={"first_rows": [{"first": value} for value in values]},
        bindings=RelationTypeBindings(inputs={"first_rows": _int_table("first")}),
    ) == evaluate_relation(
        right_associated,
        inputs={"first_rows": [{"first": value} for value in values]},
        bindings=RelationTypeBindings(inputs={"first_rows": _int_table("first")}),
    )


def test_parameter_data_owns_its_containers_and_returns_detached_snapshots() -> None:
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
    series_snapshot = parameters.snapshot_series()
    table_snapshot = parameters.snapshot_tables()
    series_snapshot["offsets"][0] = 30
    table_snapshot["calibrations"][0]["value"] = 50

    assert parameters.scalar("gain") == 1
    assert parameters.series_values("offsets") == [2, 3]
    assert parameters.table_rows("calibrations") == [{"id": "r0", "value": 4}]


def test_point_overlay_fork_replaces_a_cell_without_mutating_base_data() -> None:
    base = ParameterRelationData(tables={"calibrations": [{"id": "r0", "value": 1}]})
    point_parameters = base.fork_for_point_overlays()

    point_parameters.replace_table_cell(
        "calibrations",
        row_index=0,
        column_id="value",
        value=2,
    )

    assert point_parameters.table_rows("calibrations") == [{"id": "r0", "value": 2}]
    assert base.table_rows("calibrations") == [{"id": "r0", "value": 1}]


def test_evaluation_validates_only_used_typed_imports() -> None:
    bindings = RelationTypeBindings(inputs={"used": _INT, "unused": _INT})
    valid = ParameterRelationData().to_context(
        inputs={"used": 1, "unused": "not-an-int"}
    )

    assert (
        evaluate_scalar(
            input_ref("used"),
            valid,
            bindings=bindings,
        )
        == 1
    )

    invalid = ParameterRelationData().to_context(
        inputs={"used": "not-an-int", "unused": 1}
    )
    with pytest.raises(ValueValidationError, match=r"inputs\.used: expected int"):
        evaluate_scalar(
            input_ref("used"),
            invalid,
            bindings=bindings,
        )


def test_evaluation_validates_used_parameter_contracts() -> None:
    ctx = ParameterRelationData(scalars={"gain": "not-an-int"}).to_context()

    with pytest.raises(ValueValidationError, match=r"parameters\.gain: expected int"):
        evaluate_scalar(
            param("gain"),
            ctx,
            bindings=RelationTypeBindings(parameters={"gain": _INT}),
        )


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
            ParameterRelationData().to_context(inputs={"value": raw}),
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
            inputs={"rows": [{"extra": object()}]},
            bindings=RelationTypeBindings(inputs={"rows": open_rows}),
        )


@pytest.mark.parametrize("role", ["current", "outer", "point", "argument"])
def test_evaluation_validates_used_row_roles(role: str) -> None:
    row_scope_id = _row_scope("external")
    row: Row = {"value": "not-an-int"}
    if role == "current":
        expression = col("value")
        bindings = RelationTypeBindings(current_row=_int_row("value"))
        ctx = ParameterRelationData().to_context(row=row)
    elif role == "outer":
        expression = outer("value")
        bindings = RelationTypeBindings(outer_row=_int_row("value"))
        ctx = ParameterRelationData().to_context(outer_row=row)
    elif role == "point":
        expression = point_col("value")
        bindings = RelationTypeBindings(point_row=_int_row("value"))
        ctx = ParameterRelationData().to_context(point_row=row)
    else:
        expression = col("value", row_scope_id=row_scope_id)
        bindings = RelationTypeBindings(row_arguments={row_scope_id: _int_row("value")})
        ctx = ParameterRelationData().to_context(row_scopes={row_scope_id: row})

    with pytest.raises(ValueValidationError, match="expected int"):
        evaluate_scalar(
            expression,
            ctx,
            bindings=bindings,
        )


def test_evaluation_validates_implicit_point_cross_row_contract() -> None:
    plan = literal_rows([{"axis": 1}]).point_cross(literal_rows([{}]))

    with pytest.raises(ValueValidationError, match="unknown columns: axis"):
        evaluate_relation(
            plan,
            point_row={"axis": 9},
            bindings=RelationTypeBindings(point_row=RowType()),
        )
