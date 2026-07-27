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
    input_table,
    lit,
    param,
    parameter_lookup,
    point_col,
)
from scopecat.kernel.value_types import (
    Float,
    Scalar,
    String,
)

_FLOAT = Scalar(Float())


def test_plan_input_refs_cover_each_value_shape() -> None:
    repeated = input_ref("shared") + input_ref("shared")

    assert plan_input_refs(repeated) == ("shared",)
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
