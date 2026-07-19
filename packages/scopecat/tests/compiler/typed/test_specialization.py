from __future__ import annotations

from scopecat.compiler.relations.evaluation import EvalContext, ParameterRelationData
from scopecat.compiler.relations.model import (
    LiteralRowsRelationExpr,
    LiteralScalarExpr,
    ValuesSeriesExpr,
    col,
    grid,
    param,
    parameter_series,
    point_col,
    table,
)
from scopecat.compiler.relations.point_domain import (
    POINT_UNIT,
    PointDependentProduct,
    PointProduct,
    PointRelationRows,
    PointUnit,
    point_dependent_product,
    point_product,
    point_rows,
)
from scopecat.compiler.relations.specialization import BindingTime
from scopecat.compiler.relations.uses import RelationUse, relation_use
from scopecat.compiler.relations.verification import RelationTypeBindings, RowType
from scopecat.compiler.semantic.compute_result import ComputeResultRef
from scopecat.compiler.semantic.model import (
    ActionId,
    DomainInputPortDef,
    DomainProgramId,
    OperationId,
    operation_result_id,
)
from scopecat.compiler.semantic.operation_contract import (
    LOCAL_OPAQUE_OPERATION_CONTRACT,
)
from scopecat.compiler.semantic.value_expressions import (
    SeriesValueExpr,
    TableValueExpr,
)
from scopecat.compiler.typed.action import ActionFieldSpec, ActionSpec
from scopecat.compiler.typed.parameter_overlays import PointParameterOverlay
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.program import (
    ComputeEdge,
    CoreProgram,
    ResourceRouteIntent,
    TypedComputeNode,
    TypedComputeOutput,
    TypedDomainExecution,
    TypedDomainProgram,
    ValueInput,
    set_state_field,
)
from scopecat.compiler.typed.specialization import (
    specialize_core_program,
    specialize_value_expression,
)
from scopecat.compiler.typed.state import SetStateSpec
from scopecat.kernel.resource_identity import logical_resource_port_id
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import (
    Float,
    Int,
    Scalar,
    Series,
    String,
    Table,
    TableColumn,
)
from tests.testkit.relation_plans import (
    scalar_value_expr,
    series_value_expr,
    table_value_expr,
)


def test_core_specialization_folds_scalar_inputs_across_effect_kinds() -> None:
    value_type = Scalar(Float())
    config_value = scalar_value_expr(
        param("gain"),
        bindings=RelationTypeBindings(parameters={"gain": value_type}),
        expected_type=value_type,
    )
    domain = TypedDomainExecution(
        id="domain",
        program=TypedDomainProgram(
            id=DomainProgramId(SymbolId(local_id="program")),
            dialect_id="tests.specialization",
            dialect_version="1",
            body=(),
            input_ports=(DomainInputPortDef("gain", value_type),),
        ),
        inputs={"gain": ValueInput(config_value)},
    )
    state = set_state_field(
        scalar_value_expr("source-0", expected_type=Scalar(String())),
        capability_id="drive",
        field_path="gain",
        value=config_value,
    )
    action = ActionSpec(
        id=ActionId(SymbolId(local_id="pulse")),
        resource_port_id=logical_resource_port_id("drive"),
        capability_id="pulse",
        fields=(ActionFieldSpec("gain", relation_use(config_value)),),
    )
    specialized = specialize_core_program(
        CoreProgram(
            id="specialized",
            kind="test",
            point_domain=PointDomain(POINT_UNIT),
            effects=(state, action, domain),
        ),
        parameters=ParameterRelationData(scalars={"gain": 2.5}),
    )

    specialized_state = specialized.effects[0]
    assert isinstance(specialized_state, SetStateSpec)
    state_value = specialized_state.value_use
    assert isinstance(state_value, RelationUse)
    assert isinstance(state_value.value.plan.root, LiteralScalarExpr)
    specialized_action = specialized.effects[1]
    assert isinstance(specialized_action, ActionSpec)
    action_value = specialized_action.fields[0].value_use
    assert isinstance(action_value, RelationUse)
    assert isinstance(action_value.value.plan.root, LiteralScalarExpr)
    specialized_domain = specialized.effects[2]
    assert isinstance(specialized_domain, TypedDomainExecution)
    domain_input = specialized_domain.inputs["gain"]
    assert isinstance(domain_input.value.plan.root, LiteralScalarExpr)


def test_value_specialization_folds_series_and_table_parameters() -> None:
    integer = Scalar(Int())
    series_type = Series(integer, min_length=2, max_length=2)
    table_type = Table(
        (TableColumn("x", integer),),
        min_rows=0,
        max_rows=2,
    )
    bindings = RelationTypeBindings(
        parameters={"values": series_type, "rows": table_type}
    )
    parameters = ParameterRelationData(
        series={"values": [1, 2]},
        tables={"rows": [{"x": 3}, {"x": 4}]},
    )

    specialized_series, series_binding_time = specialize_value_expression(
        series_value_expr(
            parameter_series("values"),
            bindings=bindings,
            expected_type=series_type,
        ),
        known=EvalContext(params=parameters),
        parameter_cells=(),
    )
    specialized_table, table_binding_time = specialize_value_expression(
        table_value_expr(
            table("rows").filter(col("x").gt(2)),
            bindings=bindings,
            expected_type=table_type,
        ),
        known=EvalContext(params=parameters),
        parameter_cells=(),
    )

    assert isinstance(specialized_series, SeriesValueExpr)
    assert isinstance(specialized_series.plan.root, ValuesSeriesExpr)
    assert specialized_series.plan.root.items == [1, 2]
    assert specialized_series.value_type.min_length == 2
    assert specialized_series.value_type.max_length == 2
    assert series_binding_time is BindingTime.CONFIGURATION_STATIC
    assert isinstance(specialized_table, TableValueExpr)
    assert isinstance(specialized_table.plan.root, LiteralRowsRelationExpr)
    assert specialized_table.plan.root.rows == [{"x": 3}, {"x": 4}]
    assert specialized_table.value_type.min_rows == 2
    assert specialized_table.value_type.max_rows == 2
    assert table_binding_time is BindingTime.CONFIGURATION_STATIC


def test_core_specialization_folds_series_route_entities() -> None:
    integer = Scalar(Int())
    series_type = Series(integer, min_length=2, max_length=2)
    route_entities = series_value_expr(
        parameter_series("entities"),
        bindings=RelationTypeBindings(parameters={"entities": series_type}),
        expected_type=series_type,
    )

    specialized = specialize_core_program(
        CoreProgram(
            id="route-specialized",
            kind="test",
            point_domain=PointDomain(POINT_UNIT),
            route_intents=(
                ResourceRouteIntent(
                    port_id=logical_resource_port_id("drive"),
                    entity_uses=(relation_use(route_entities),),
                ),
            ),
        ),
        parameters=ParameterRelationData(series={"entities": [1, 2]}),
    )

    root = specialized.route_intents[0].entity_uses[0].value.plan.root
    assert isinstance(root, ValuesSeriesExpr)
    assert root.items == [1, 2]


def test_core_specialization_collapses_point_independent_dependent_product() -> None:
    integer = Scalar(Int())
    left_type = Table(
        (TableColumn("x", integer),),
        min_rows=1,
        max_rows=1,
    )
    right_type = Table(
        (TableColumn("y", integer),),
        min_rows=2,
        max_rows=2,
    )
    left = table_value_expr(
        LiteralRowsRelationExpr([{"x": 1}]),
        expected_type=left_type,
    )
    right = table_value_expr(
        table("right"),
        bindings=RelationTypeBindings(parameters={"right": right_type}),
        expected_type=right_type,
    )

    specialized = specialize_core_program(
        CoreProgram(
            id="point-specialized",
            kind="test",
            point_domain=PointDomain(
                point_dependent_product(point_rows(left), point_rows(right))
            ),
        ),
        parameters=ParameterRelationData(tables={"right": [{"y": 2}, {"y": 3}]}),
    )

    root = specialized.point_domain.root
    assert isinstance(root, PointProduct)
    assert specialized.point_domain.value_type.min_rows == 2
    assert specialized.point_domain.value_type.max_rows == 2
    assert all(isinstance(factor, PointRelationRows) for factor in root.factors)
    assert all(
        isinstance(factor.rows.plan.root, LiteralRowsRelationExpr)
        for factor in root.factors
        if isinstance(factor, PointRelationRows)
    )


def test_core_specialization_prunes_dead_compute_nodes() -> None:
    value_type = Scalar(Float())

    def compute(
        name: str, upstream: TypedComputeNode | None = None
    ) -> TypedComputeNode:
        operation_id = OperationId(SymbolId(local_id=name))
        return TypedComputeNode(
            id=operation_id,
            contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
            result=TypedComputeOutput(
                id=operation_result_id(operation_id),
                value_type=value_type,
            ),
            inputs=(
                {}
                if upstream is None
                else {
                    "upstream": ComputeEdge(
                        upstream.result.id,
                        expected_type=value_type,
                    )
                }
            ),
        )

    upstream = compute("upstream")
    live = compute("live", upstream)
    dead = compute("dead")
    action = ActionSpec(
        id=ActionId(SymbolId(local_id="consume")),
        resource_port_id=logical_resource_port_id("drive"),
        capability_id="pulse",
        fields=(ActionFieldSpec("payload", ComputeResultRef(live.result.id)),),
    )

    specialized = specialize_core_program(
        CoreProgram(
            id="dce",
            kind="test",
            point_domain=PointDomain(POINT_UNIT),
            compute_nodes=(upstream, live, dead),
            effects=(action,),
        ),
        parameters=ParameterRelationData(),
    )

    assert tuple(node.id for node in specialized.compute_nodes) == (
        upstream.id,
        live.id,
    )


def test_core_specialization_reduces_single_empty_row_point_leaf_to_unit() -> None:
    unit_table = Table(columns=(), min_rows=1, max_rows=1)
    leaf = table_value_expr(
        LiteralRowsRelationExpr([{}]),
        expected_type=unit_table,
    )

    specialized = specialize_core_program(
        CoreProgram(
            id="unit-specialized",
            kind="test",
            point_domain=PointDomain(point_rows(leaf)),
        ),
        parameters=ParameterRelationData(),
    )

    assert isinstance(specialized.point_domain.root, PointUnit)


def test_core_specialization_collapses_known_empty_point_composition() -> None:
    integer = Scalar(Int())
    left_type = Table(
        (TableColumn("x", integer),),
        min_rows=1,
        max_rows=1,
    )
    right_type = Table(
        (TableColumn("y", integer),),
        min_rows=0,
        max_rows=2,
    )
    left = table_value_expr(
        LiteralRowsRelationExpr([{"x": 1}]),
        expected_type=left_type,
    )
    right = table_value_expr(
        table("empty"),
        bindings=RelationTypeBindings(parameters={"empty": right_type}),
        expected_type=right_type,
    )

    specialized = specialize_core_program(
        CoreProgram(
            id="empty-specialized",
            kind="test",
            point_domain=PointDomain(
                point_product(point_rows(left), point_rows(right))
            ),
        ),
        parameters=ParameterRelationData(tables={"empty": []}),
    )

    root = specialized.point_domain.root
    assert isinstance(root, PointRelationRows)
    assert isinstance(root.rows.plan.root, LiteralRowsRelationExpr)
    assert root.rows.plan.root.rows == []
    assert tuple(column.id for column in root.rows.value_type.columns) == ("x", "y")
    assert root.rows.value_type.max_rows == 0


def test_core_specialization_retains_genuinely_point_dependent_product() -> None:
    integer = Scalar(Int())
    left_type = Table(
        (TableColumn("x", integer),),
        min_rows=1,
        max_rows=1,
    )
    right_type = Table(
        (TableColumn("y", integer),),
        min_rows=1,
        max_rows=1,
    )
    left = table_value_expr(
        LiteralRowsRelationExpr([{"x": 1}]),
        expected_type=left_type,
    )
    right = table_value_expr(
        grid(y=point_col("x")),
        bindings=RelationTypeBindings(point_row=RowType.from_table(left_type)),
        expected_type=right_type,
    )

    specialized = specialize_core_program(
        CoreProgram(
            id="dependent-specialized",
            kind="test",
            point_domain=PointDomain(
                point_dependent_product(point_rows(left), point_rows(right))
            ),
        ),
        parameters=ParameterRelationData(),
    )

    assert isinstance(specialized.point_domain.root, PointDependentProduct)


def test_core_specialization_folds_parameter_overlay_keys() -> None:
    integer = Scalar(Int())
    key = scalar_value_expr(
        param("selected"),
        bindings=RelationTypeBindings(parameters={"selected": integer}),
        expected_type=integer,
    )
    value = scalar_value_expr(
        point_col("scan"),
        bindings=RelationTypeBindings(
            point_row=RowType((TableColumn("scan", integer),))
        ),
        expected_type=integer,
    )
    overlay = PointParameterOverlay(
        table_id="devices",
        key_uses={"id": relation_use(key)},
        column_id="value",
        value_use=relation_use(value),
    )

    specialized = specialize_core_program(
        CoreProgram(
            id="overlay-specialized",
            kind="test",
            point_domain=PointDomain(POINT_UNIT),
            parameter_overlays=(overlay,),
        ),
        parameters=ParameterRelationData(
            scalars={"selected": 1},
            tables={"devices": [{"id": 1, "value": 0}]},
        ),
    )

    key_root = specialized.parameter_overlays[0].key_uses["id"].value.plan.root
    assert isinstance(key_root, LiteralScalarExpr)
    assert key_root.value == 1
