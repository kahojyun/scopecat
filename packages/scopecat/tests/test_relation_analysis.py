import pytest

from scopecat._compiler.dependencies import analyze_compute_dependencies
from scopecat._compiler.program import TypedComputeNode, TypedComputeOutput, ValueInput
from scopecat._operation_contract import LOCAL_OPAQUE_OPERATION_CONTRACT
from scopecat._relation_analysis import (
    PlanReference,
    PlanReferenceKind,
    RelationOperation,
    RelationPlanBinderError,
    free_row_references,
    iter_plan_children,
    plan_input_refs,
    plan_references,
    relation_operation,
    verify_plan_scopes,
    walk_plan,
)
from scopecat._relation_verification import RelationTypeBindings, RowType
from scopecat._relations import (
    GridColumn,
    RelationExpr,
    RowScopeId,
    ScalarExpr,
    SeriesExpr,
    col,
    input_ref,
    input_series,
    input_table,
    lit,
    literal_rows,
    outer,
    param,
    parameter_series,
    point_col,
    table,
)
from scopecat._semantic_graph import OperationId, operation_result_id
from scopecat._symbols import SymbolId
from scopecat._value_availability import ValueAvailability, ValueRate, ValueStage
from scopecat.value_types import Bool, Float, Scalar, Series, Table, TableColumn
from tests.support.relation_plans import value_expr


@pytest.mark.parametrize("operation", list(RelationOperation))
def test_relation_operation_is_exhaustive_and_shape_qualified(
    operation: RelationOperation,
) -> None:
    shape, kind = operation.value.split(".", maxsplit=1)
    node_type = {
        "scalar": ScalarExpr,
        "series": SeriesExpr,
        "relation": RelationExpr,
    }[shape]
    node = node_type.model_construct(kind=kind)

    assert relation_operation(node) is operation


def test_relation_operation_rejects_unknown_plan_kinds() -> None:
    unknown = ScalarExpr.model_construct(kind="future_scalar")

    with pytest.raises(ValueError, match="unsupported scalar plan operation"):
        relation_operation(unknown)


def test_plan_input_refs_deduplicate_ids_across_shapes() -> None:
    plan = RelationExpr(
        kind="grid",
        columns={
            "scalar": GridColumn(kind="scalar", scalar=input_ref("shared")),
            "series": GridColumn(kind="series", series=input_series("shared")),
            "table": GridColumn(kind="relation", relation=input_table("shared")),
        },
    )

    assert plan_input_refs(plan) == ("shared",)


def test_free_row_references_exclude_plan_local_binders() -> None:
    local_scope = RowScopeId(SymbolId(local_id="local"))
    foreign_scope = RowScopeId(SymbolId(local_id="foreign"))
    closed = literal_rows([{"value": 1}]).with_columns(
        row_scope_id=local_scope,
        copied=col("value", row_scope_id=local_scope),
    )
    captured = closed.with_columns(
        leaked=col("value", row_scope_id=foreign_scope),
    )

    assert free_row_references(closed).references == frozenset()
    assert free_row_references(captured).references == frozenset(
        {
            PlanReference(
                PlanReferenceKind.CURRENT_COLUMN,
                "value",
                row_scope_id=foreign_scope,
            )
        }
    )


def test_nominal_row_binders_cannot_shadow_an_enclosing_identity() -> None:
    scope = RowScopeId(SymbolId(local_id="row"))
    filtered = literal_rows([{"value": 1}]).filter(
        col("value", row_scope_id=scope).gt(0),
        row_scope_id=scope,
    )
    reused = filtered.cross(
        filtered.with_columns(
            copied=col("value"),
        )
    )

    verify_plan_scopes(reused)
    with pytest.raises(RelationPlanBinderError, match="collides with an enclosing"):
        verify_plan_scopes(filtered, active_row_scopes=(scope,))


def test_plan_walk_and_references_cover_every_nested_shape() -> None:
    lookup = param(
        "calibrations",
        key={
            "local": col("local_id"),
            "point": point_col("point_id"),
        },
        column="gain",
    )
    left = RelationExpr(
        kind="grid",
        columns={
            "sweep": GridColumn(
                kind="series",
                series=SeriesExpr(
                    kind="range",
                    start=input_ref("start"),
                    stop=param("stop"),
                    step=lit(1.0),
                ),
            ),
            "input_offsets": GridColumn(
                kind="series",
                series=input_series("offsets"),
            ),
            "configured_offsets": GridColumn(
                kind="series",
                series=parameter_series("configured_offsets"),
            ),
            "rows": GridColumn(
                kind="relation",
                relation=input_table("rows"),
            ),
        },
    )
    right = (
        table("records")
        .filter(input_ref("enabled"))
        .with_columns(
            gain=lookup,
            outer_flag=outer("outer_flag"),
        )
    )
    plan = left.lateral_cross(right)

    assert tuple(iter_plan_children(plan)) == (left, right)
    assert relation_operation(next(walk_plan(plan))) is (
        RelationOperation.RELATION_LATERAL_CROSS
    )
    assert plan_references(plan).references == frozenset(
        {
            PlanReference(PlanReferenceKind.CURRENT_COLUMN, "local_id"),
            PlanReference(PlanReferenceKind.OUTER_COLUMN, "outer_flag"),
            PlanReference(PlanReferenceKind.POINT_COLUMN, "point_id"),
            PlanReference(PlanReferenceKind.INPUT_SCALAR, "enabled"),
            PlanReference(PlanReferenceKind.INPUT_SCALAR, "start"),
            PlanReference(PlanReferenceKind.INPUT_SERIES, "offsets"),
            PlanReference(PlanReferenceKind.INPUT_TABLE, "rows"),
            PlanReference(PlanReferenceKind.PARAMETER_SCALAR, "stop"),
            PlanReference(
                PlanReferenceKind.PARAMETER_SERIES,
                "configured_offsets",
            ),
            PlanReference(PlanReferenceKind.PARAMETER_TABLE, "calibrations"),
            PlanReference(PlanReferenceKind.PARAMETER_TABLE, "records"),
        }
    )
    assert plan_input_refs(plan) == ("enabled", "offsets", "rows", "start")


def test_compute_dependencies_project_shared_plan_references() -> None:
    operation_id = OperationId(SymbolId(local_id="consume-plan"))
    bool_type = Scalar(Bool())
    rows_type = Table(
        columns=(TableColumn("local_enabled", bool_type),),
        allow_extra_columns=True,
    )
    offsets_type = Series(Scalar(Float()))
    bindings = RelationTypeBindings(
        inputs={
            "rows": rows_type,
            "enabled": bool_type,
            "offsets": offsets_type,
        },
        parameters={"gain": Scalar(Float())},
        point_row=RowType((TableColumn("point_enabled", bool_type),)),
        outer_row=RowType((TableColumn("outer_enabled", bool_type),)),
    )
    plan = input_table("rows").filter(
        input_ref("enabled").and_(
            point_col("point_enabled")
            .and_(outer("outer_enabled"))
            .and_(col("local_enabled"))
        )
    )
    node = TypedComputeNode(
        id=operation_id,
        contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
        inputs={
            "rows": ValueInput(
                value=value_expr(
                    plan,
                    expected_type=rows_type,
                    bindings=bindings,
                ),
                origin_input_ids=("authored_rows",),
            ),
            "gain": ValueInput(
                value=value_expr(
                    param("gain"),
                    expected_type=Scalar(Float()),
                    bindings=bindings,
                ),
            ),
            "offsets": ValueInput(
                value=value_expr(
                    input_series("offsets"),
                    expected_type=offsets_type,
                    bindings=bindings,
                ),
                origin_input_ids=("authored_offsets",),
            ),
        },
        result=TypedComputeOutput(
            id=operation_result_id(operation_id),
            value_type=Scalar(Float()),
            availability=ValueAvailability(ValueStage.EXECUTE, ValueRate.POINT),
        ),
    )

    dependencies = analyze_compute_dependencies((node,))[operation_id]

    assert dependencies.as_mapping() == {
        "point_columns": ("point_enabled",),
        "input_refs": (
            "authored_offsets",
            "authored_rows",
            "enabled",
            "offsets",
            "rows",
        ),
        "parameters": ("gain",),
    }
