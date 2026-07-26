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
    iter_plan_children,
    plan_input_refs,
    plan_references,
    rewrite_plan,
)
from scopecat.graph.relations.model import (
    InputScalarExpr,
    ParameterLookupUse,
    input_ref,
    input_series,
    input_table,
    lit,
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
    Float,
    Scalar,
    Series,
    String,
    Table,
    TableColumn,
)
from tests.testkit.relation_plans import value_expr

_FLOAT = Scalar(Float())


def _implementation(operation_id: OperationId) -> LocalPythonImplementation:
    return LocalPythonImplementation(
        id=ImplementationId(f"python.{operation_id.qualified_name}"),
        kernel=lambda: None,
    )


def test_plan_input_refs_cover_each_value_shape() -> None:
    repeated = input_ref("shared") + input_ref("shared")

    assert plan_input_refs(repeated) == ("shared",)
    assert plan_input_refs(input_series("shared")) == ("shared",)
    assert plan_input_refs(input_table("shared")) == ("shared",)


def test_plan_walk_rewrite_and_references_cover_nested_scalars() -> None:
    lookup = parameter_lookup(
        ParameterLookupUse(
            table_id="calibrations",
            key_input_types=(
                ("device", Scalar(String())),
                ("point", Scalar(String())),
            ),
            literal_key_columns=frozenset(),
            column_id="gain",
            result_type=_FLOAT,
        ),
        key={
            "device": input_ref("device"),
            "point": point_col("point_id"),
        },
    )
    plan = input_ref("start") + lookup + param("stop")

    assert tuple(iter_plan_children(plan)) == (plan.left, plan.right)
    assert plan_references(plan).references == frozenset(
        {
            PlanReference(PlanReferenceKind.INPUT_SCALAR, "device"),
            PlanReference(PlanReferenceKind.INPUT_SCALAR, "start"),
            PlanReference(PlanReferenceKind.POINT_COLUMN, "point_id"),
            PlanReference(PlanReferenceKind.PARAMETER_SCALAR, "stop"),
            PlanReference(PlanReferenceKind.PARAMETER_TABLE, "calibrations"),
        }
    )

    rewritten = rewrite_plan(
        plan,
        lambda node: lit(1.0) if isinstance(node, InputScalarExpr) else node,
    )
    assert plan_references(rewritten).ids(PlanReferenceKind.INPUT_SCALAR) == ()


def test_compute_dependencies_project_shared_plan_references() -> None:
    operation_id = OperationId(SymbolId(local_id="consume-plan"))
    rows_type = Table(columns=(TableColumn("value", _FLOAT),))
    offsets_type = Series(_FLOAT)
    bindings = RelationTypeBindings(
        inputs={
            "rows": rows_type,
            "offset": _FLOAT,
            "offsets": offsets_type,
        },
        parameters={"gain": _FLOAT},
        point_row=RowType((TableColumn("point_offset", _FLOAT),)),
    )
    node = TypedComputeNode(
        id=operation_id,
        contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
        implementation=_implementation(operation_id),
        inputs={
            "rows": ValueInput(
                value=value_expr(
                    input_table("rows"),
                    expected_type=rows_type,
                    bindings=bindings,
                ),
                origin_input_ids=("authored_rows",),
            ),
            "selected": ValueInput(
                value=value_expr(
                    input_ref("offset") + point_col("point_offset"),
                    expected_type=_FLOAT,
                    bindings=bindings,
                ),
            ),
            "gain": ValueInput(
                value=value_expr(
                    param("gain"),
                    expected_type=_FLOAT,
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
            value_type=_FLOAT,
        ),
    )

    dependencies = analyze_compute_dependencies((node,))[operation_id]

    assert dependencies.as_mapping() == {
        "point_columns": ("point_offset",),
        "input_refs": (
            "authored_offsets",
            "authored_rows",
            "offset",
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
                    expected_type=_FLOAT,
                    bindings=RelationTypeBindings(
                        point_row=RowType((TableColumn("frequency", _FLOAT),))
                    ),
                )
            )
        },
        result=ComputeOutput(id=producer_output, value_type=_FLOAT),
    )
    consumer = TypedComputeNode(
        id=consumer_id,
        contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
        implementation=_implementation(consumer_id),
        inputs={
            "value": ComputeEdge(
                value_id=producer_output,
                expected_type=_FLOAT,
            )
        },
        result=ComputeOutput(
            id=operation_result_id(consumer_id),
            value_type=_FLOAT,
        ),
    )

    dependencies = analyze_compute_dependencies((producer, consumer))

    assert dependencies[producer_id].scope is ComputeScope.POINT
    assert dependencies[consumer_id].scope is ComputeScope.POINT
