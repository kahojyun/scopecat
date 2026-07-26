import pytest

from scopecat.compiler.relations.verification import (
    RelationTypeBindings,
    RowType,
)
from scopecat.compiler.semantic.model import (
    ImplementationId,
    LocalPythonImplementation,
)
from scopecat.compiler.semantic.operation_contract import (
    LOCAL_OPAQUE_OPERATION_CONTRACT,
)
from scopecat.compiler.typed.dependencies import (
    ComputeScope,
    analyze_compute_dependencies,
)
from scopecat.compiler.typed.program import (
    ComputeEdge,
    TypedComputeNode,
    ValueInput,
)
from scopecat.graph.relations.analysis import (
    PlanReference,
    PlanReferenceKind,
    RelationPlanBinderError,
    free_row_references,
    iter_plan_children,
    plan_input_refs,
    plan_references,
    prefix_plan_row_scopes,
    rewrite_plan,
    verify_plan_scopes,
)
from scopecat.graph.relations.model import (
    ColumnScalarExpr,
    InputScalarExpr,
    ParameterLookupUse,
    RowScopeId,
    col,
    input_ref,
    input_series,
    input_table,
    lit,
    literal_rows,
    param,
    parameter_lookup,
    point_col,
)
from scopecat.graph.values import (
    ComputeOutput,
    OperationId,
    operation_result_id,
)
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import (
    Bool,
    Float,
    Scalar,
    Series,
    String,
    Table,
    TableColumn,
)
from tests.testkit.relation_plans import value_expr


def _implementation(operation_id: OperationId) -> LocalPythonImplementation:
    return LocalPythonImplementation(
        id=ImplementationId(f"python.{operation_id.qualified_name}"),
        kernel=lambda: None,
    )


def _scope(local_id: str) -> RowScopeId:
    return RowScopeId(SymbolId(local_id=local_id))


def test_plan_input_refs_deduplicate_scalar_and_table_refs() -> None:
    plan = input_table("shared").with_columns(
        row_scope_id=_scope("input-refs"),
        copied=input_ref("shared"),
    )

    assert plan_input_refs(plan) == ("shared",)
    assert plan_input_refs(input_series("shared")) == ("shared",)


def test_free_row_references_exclude_plan_local_binders() -> None:
    local_scope = RowScopeId(SymbolId(local_id="local"))
    foreign_scope = RowScopeId(SymbolId(local_id="foreign"))
    closed = literal_rows([{"value": 1}]).with_columns(
        row_scope_id=local_scope,
        copied=col("value", row_scope_id=local_scope),
    )
    captured_scope = _scope("captured")
    captured = closed.with_columns(
        row_scope_id=captured_scope,
        leaked=col("value", row_scope_id=foreign_scope),
    )

    assert free_row_references(closed).references == frozenset()
    assert free_row_references(captured).references == frozenset(
        {
            PlanReference(
                PlanReferenceKind.ROW_COLUMN,
                "value",
                row_scope_id=foreign_scope,
            )
        }
    )


def test_nominal_row_binders_cannot_shadow_an_enclosing_identity() -> None:
    scope = RowScopeId(SymbolId(local_id="row"))
    bound = literal_rows([{"value": 1}]).with_columns(
        row_scope_id=scope,
        copied=col("value", row_scope_id=scope),
    )
    reused_scope = _scope("reused")
    reused = bound.with_columns(
        row_scope_id=reused_scope,
        copied=col("value", row_scope_id=reused_scope),
    )

    verify_plan_scopes(reused)
    with pytest.raises(RelationPlanBinderError, match="collides with an enclosing"):
        verify_plan_scopes(bound, active_row_scopes=(scope,))


def test_prefix_plan_row_scopes_alpha_renames_binders_and_uses_together() -> None:
    scope = _scope("row")
    plan = literal_rows([{"value": 1}]).with_columns(
        row_scope_id=scope,
        copied=col("value", row_scope_id=scope),
    )

    prefixed = prefix_plan_row_scopes(plan, "module", "use")

    expected = scope.prefixed("module", "use")
    assert prefixed.row_scope_id == expected
    copied = prefixed.new_columns["copied"]
    assert isinstance(copied, ColumnScalarExpr)
    assert copied.row_scope_id == expected
    assert plan.row_scope_id == scope
    verify_plan_scopes(prefixed)


def test_plan_walk_and_references_cover_every_nested_shape() -> None:
    columns_scope = _scope("columns")
    lookup = parameter_lookup(
        ParameterLookupUse(
            table_id="calibrations",
            key_input_types=(
                ("local", Scalar(String())),
                ("point", Scalar(String())),
            ),
            literal_key_columns=frozenset(),
            column_id="gain",
            result_type=Scalar(Float()),
        ),
        key={
            "local": col("local_id", row_scope_id=columns_scope),
            "point": point_col("point_id"),
        },
    )
    plan = input_table("rows").with_columns(
        row_scope_id=columns_scope,
        enabled=input_ref("enabled"),
        start=input_ref("start"),
        gain=lookup,
        stop=param("stop"),
    )

    assert tuple(iter_plan_children(plan)) == (
        plan.source,
        plan.new_columns["enabled"],
        plan.new_columns["start"],
        plan.new_columns["gain"],
        plan.new_columns["stop"],
    )
    assert plan_references(plan).references == frozenset(
        {
            PlanReference(
                PlanReferenceKind.ROW_COLUMN,
                "local_id",
                row_scope_id=columns_scope,
            ),
            PlanReference(PlanReferenceKind.POINT_COLUMN, "point_id"),
            PlanReference(PlanReferenceKind.INPUT_SCALAR, "enabled"),
            PlanReference(PlanReferenceKind.INPUT_SCALAR, "start"),
            PlanReference(PlanReferenceKind.INPUT_TABLE, "rows"),
            PlanReference(PlanReferenceKind.PARAMETER_SCALAR, "stop"),
            PlanReference(PlanReferenceKind.PARAMETER_TABLE, "calibrations"),
        }
    )
    assert plan_input_refs(plan) == ("enabled", "rows", "start")

    rewritten = rewrite_plan(
        plan,
        lambda node: lit(True) if isinstance(node, InputScalarExpr) else node,
    )
    assert plan_references(rewritten).ids(PlanReferenceKind.INPUT_SCALAR) == ()
    assert plan_references(rewritten).ids(PlanReferenceKind.INPUT_TABLE) == ("rows",)


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
    )
    columns_scope = _scope("compute-columns")
    plan = input_table("rows").with_columns(
        row_scope_id=columns_scope,
        selected=input_ref("enabled").and_(
            point_col("point_enabled").and_(
                col("local_enabled", row_scope_id=columns_scope)
            )
        ),
    )
    node = TypedComputeNode(
        id=operation_id,
        contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
        implementation=_implementation(operation_id),
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
        result=ComputeOutput(
            id=operation_result_id(operation_id),
            value_type=Scalar(Float()),
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
    assert dependencies.scope is ComputeScope.POINT


def test_compute_scope_propagates_through_compute_edges() -> None:
    producer_id = OperationId(SymbolId(local_id="producer"))
    consumer_id = OperationId(SymbolId(local_id="consumer"))
    producer_output = operation_result_id(producer_id)
    producer = TypedComputeNode(
        id=producer_id,
        contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
        implementation=_implementation(producer_id),
        inputs={
            "coordinate": ValueInput(
                value=value_expr(
                    point_col("frequency"),
                    expected_type=Scalar(Float()),
                    bindings=RelationTypeBindings(
                        point_row=RowType((TableColumn("frequency", Scalar(Float())),))
                    ),
                )
            )
        },
        result=ComputeOutput(
            id=producer_output,
            value_type=Scalar(Float()),
        ),
    )
    consumer = TypedComputeNode(
        id=consumer_id,
        contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
        implementation=_implementation(consumer_id),
        inputs={
            "value": ComputeEdge(
                value_id=producer_output,
                expected_type=Scalar(Float()),
            )
        },
        result=ComputeOutput(
            id=operation_result_id(consumer_id),
            value_type=Scalar(Float()),
        ),
    )

    dependencies = analyze_compute_dependencies((producer, consumer))

    assert dependencies[producer_id].scope is ComputeScope.POINT
    assert dependencies[consumer_id].scope is ComputeScope.POINT
