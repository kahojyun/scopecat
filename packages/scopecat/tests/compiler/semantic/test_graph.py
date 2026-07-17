from __future__ import annotations

from dataclasses import replace
from typing import cast

import pytest

from scopecat.compiler.relations.model import (
    LiteralScalarExpr,
    RelationExpr,
    RowScopeId,
    ScalarExpr,
    SeriesExpr,
    as_scalar_expr,
    col,
    grid,
    input_ref,
    literal_rows,
    point_col,
)
from scopecat.compiler.relations.verification import (
    RelationPlanVerificationError,
    RelationTypeBindings,
    RowType,
    verify_relation_plan,
)
from scopecat.compiler.semantic.availability import (
    ValueAvailability,
    ValueRate,
    ValueStage,
)
from scopecat.compiler.semantic.model import (
    ImplementationCatalog,
    ImplementationId,
    LiteralValueSource,
    LocalPythonImplementation,
    OperationId,
    OperationOutputSource,
    PlanExpressionSource,
    RouteValueSource,
    RowArgumentDef,
    SemanticGraphIR,
    SemanticOperation,
    SourceAnchor,
    SourceMap,
    StateEachRegion,
    ValueDef,
    ValueId,
    ValueUse,
    operation_result_id,
    state_each_region_id,
)
from scopecat.compiler.semantic.operation_contract import (
    LOCAL_OPAQUE_OPERATION_CONTRACT,
    PlacementConstraint,
    Portability,
    scalar_binary_operation_contract,
)
from scopecat.compiler.semantic.verification import (
    verify_implementation_catalog,
    verify_semantic_graph,
    verify_source_map,
)
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.payloads import PayloadValue
from scopecat.kernel.problems import ModelLocation
from scopecat.kernel.resource_identity import LogicalResourcePortId
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import (
    Bool,
    Float,
    Int,
    Payload,
    Route,
    Scalar,
    Table,
    TableColumn,
    ValueType,
)

FLOAT = Scalar(Float())
BOOL = Scalar(Bool())
PLAN_RUN = ValueAvailability(ValueStage.PLAN, ValueRate.RUN)
PLAN_POINT = ValueAvailability(ValueStage.PLAN, ValueRate.POINT)
EXECUTE_POINT = ValueAvailability(ValueStage.EXECUTE, ValueRate.POINT)


def _operation_id(local_id: str, *scope: str) -> OperationId:
    return OperationId(SymbolId(scope=scope, local_id=local_id))


def _value_id(local_id: str, *scope: str) -> ValueId:
    return ValueId(SymbolId(scope=scope, local_id=local_id))


def _plan_source(
    expression: ScalarExpr | SeriesExpr | RelationExpr,
    *,
    expected_type: ValueType | None = None,
    bindings: RelationTypeBindings | None = None,
) -> PlanExpressionSource:
    return PlanExpressionSource(
        verify_relation_plan(
            expression,
            expected_type=expected_type,
            bindings=bindings,
        )
    )


def _plan_value(
    local_id: str,
    *,
    value_type: ValueType = FLOAT,
    availability: ValueAvailability = PLAN_RUN,
) -> ValueDef:
    expression = (
        literal_rows([]) if isinstance(value_type, Table) else as_scalar_expr(1.0)
    )
    return ValueDef(
        id=_value_id(local_id),
        value_type=value_type,
        availability=availability,
        source=_plan_source(expression, expected_type=value_type),
    )


def _opaque_operation(
    local_id: str,
    *,
    inputs: tuple[tuple[str, ValueUse], ...] = (),
    portability: Portability = Portability.IMPLEMENTATION_DEFINED,
) -> tuple[SemanticOperation, ValueDef]:
    operation_id = _operation_id(local_id)
    result_id = operation_result_id(operation_id)
    return (
        SemanticOperation(
            id=operation_id,
            contract=replace(
                LOCAL_OPAQUE_OPERATION_CONTRACT,
                portability=portability,
            ),
            inputs=inputs,
            outputs=(("result", result_id),),
        ),
        ValueDef(
            id=result_id,
            value_type=FLOAT,
            availability=EXECUTE_POINT,
            source=OperationOutputSource(operation_id),
        ),
    )


def _binary_graph(
    *,
    left_type: ValueType = FLOAT,
    right_type: ValueType = FLOAT,
    result_type: ValueType = FLOAT,
    left_availability: ValueAvailability = PLAN_RUN,
    right_availability: ValueAvailability = PLAN_RUN,
    result_availability: ValueAvailability = PLAN_RUN,
) -> SemanticGraphIR:
    left = _plan_value(
        "left",
        value_type=left_type,
        availability=left_availability,
    )
    right = _plan_value(
        "right",
        value_type=right_type,
        availability=right_availability,
    )
    operation_id = _operation_id("add")
    result_id = operation_result_id(operation_id)
    operation = SemanticOperation(
        id=operation_id,
        contract=scalar_binary_operation_contract("+"),
        inputs=(
            ("left", ValueUse(left.id)),
            ("right", ValueUse(right.id)),
        ),
        outputs=(("result", result_id),),
    )
    result = ValueDef(
        id=result_id,
        value_type=result_type,
        availability=result_availability,
        source=OperationOutputSource(operation_id),
    )
    return SemanticGraphIR(
        value_defs=(left, right, result),
        operations=(operation,),
    )


def _problem_codes(error: CheckFailed) -> list[str]:
    return [problem.code for problem in error.problems]


def test_operation_and_value_ids_are_nominal_structural_identities() -> None:
    symbol = SymbolId(scope=("a/b",), local_id="result")
    operation_id = OperationId(symbol)
    value_id = ValueId(symbol)
    nested = OperationId(SymbolId(scope=("a", "b"), local_id="result"))

    assert type(operation_id) is not type(value_id)
    assert len({operation_id, value_id}) == 2
    assert operation_id != nested
    assert operation_id.qualified_name == "a%2Fb/result"
    assert nested.qualified_name == "a/b/result"


def test_value_use_contains_only_its_target_identity() -> None:
    value_id = _value_id("source")
    use = ValueUse(value_id)

    assert use.value_id is value_id


def test_topological_order_is_identity_based_and_declaration_independent() -> None:
    producer, producer_result = _opaque_operation("producer")
    independent, independent_result = _opaque_operation("independent")
    consumer, consumer_result = _opaque_operation(
        "consumer",
        inputs=(("value", ValueUse(producer_result.id)),),
    )
    definitions = (consumer_result, producer_result, independent_result)

    forward = verify_semantic_graph(
        SemanticGraphIR(
            value_defs=definitions,
            operations=(consumer, independent, producer),
        )
    )
    reversed_declarations = verify_semantic_graph(
        SemanticGraphIR(
            value_defs=tuple(reversed(definitions)),
            operations=(producer, independent, consumer),
        )
    )

    assert forward.graph == reversed_declarations.graph
    assert [operation.id.local_id for operation in forward.graph.operations] == [
        "independent",
        "producer",
        "consumer",
    ]


def test_verified_value_map_is_immutable_and_derived_from_normalized_graph() -> None:
    verified = verify_semantic_graph(_binary_graph())

    expected = {definition.id: definition for definition in verified.graph.value_defs}
    assert dict(verified.value_defs) == expected

    mutable_view = cast("dict[ValueId, ValueDef]", verified.value_defs)
    with pytest.raises(TypeError):
        mutable_view[_value_id("new")] = _plan_value("new")


def test_duplicate_value_definition_diagnostic_is_declaration_independent() -> None:
    first = _plan_value("duplicate")
    second = ValueDef(
        id=first.id,
        value_type=FLOAT,
        availability=EXECUTE_POINT,
        source=LiteralValueSource(True),
    )

    errors: list[CheckFailed] = []
    for definitions in ((first, second), (second, first)):
        with pytest.raises(CheckFailed) as caught:
            verify_semantic_graph(SemanticGraphIR(value_defs=definitions))
        errors.append(caught.value)

    assert [_problem_codes(error) for error in errors] == [
        ["semantic_value_definition_duplicate"],
        ["semantic_value_definition_duplicate"],
    ]
    assert errors[0].problems == errors[1].problems


def test_duplicate_operation_diagnostic_is_declaration_independent() -> None:
    operation_id = _operation_id("duplicate")
    result_id = operation_result_id(operation_id)
    first = SemanticOperation(
        id=operation_id,
        contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
        inputs=(),
        outputs=(("result", result_id),),
    )
    second = SemanticOperation(
        id=operation_id,
        contract=scalar_binary_operation_contract("+"),
        inputs=(),
        outputs=(("result", result_id),),
    )

    errors: list[CheckFailed] = []
    for operations in ((first, second), (second, first)):
        with pytest.raises(CheckFailed) as caught:
            verify_semantic_graph(SemanticGraphIR(operations=operations))
        errors.append(caught.value)

    assert [_problem_codes(error) for error in errors] == [
        ["semantic_operation_duplicate"],
        ["semantic_operation_duplicate"],
    ]
    assert errors[0].problems == errors[1].problems


def test_dangling_value_use_is_a_structured_problem() -> None:
    operation, result = _opaque_operation(
        "consumer",
        inputs=(("missing", ValueUse(_value_id("missing"))),),
    )

    with pytest.raises(CheckFailed) as caught:
        verify_semantic_graph(
            SemanticGraphIR(value_defs=(result,), operations=(operation,))
        )

    assert _problem_codes(caught.value) == ["semantic_value_use_dangling"]
    location = caught.value.problems[0].location
    assert isinstance(location, ModelLocation)
    assert location.path == (
        "consumer",
        "inputs",
        "missing",
    )


def test_operation_cycles_are_reported_in_identity_order() -> None:
    left_id = _operation_id("left")
    right_id = _operation_id("right")
    left_result = operation_result_id(left_id)
    right_result = operation_result_id(right_id)
    left = SemanticOperation(
        id=left_id,
        contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
        inputs=(("right", ValueUse(right_result)),),
        outputs=(("result", left_result),),
    )
    right = SemanticOperation(
        id=right_id,
        contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
        inputs=(("left", ValueUse(left_result)),),
        outputs=(("result", right_result),),
    )
    definitions = (
        ValueDef(
            id=left_result,
            value_type=FLOAT,
            availability=EXECUTE_POINT,
            source=OperationOutputSource(left_id),
        ),
        ValueDef(
            id=right_result,
            value_type=FLOAT,
            availability=EXECUTE_POINT,
            source=OperationOutputSource(right_id),
        ),
    )

    with pytest.raises(CheckFailed) as caught:
        verify_semantic_graph(
            SemanticGraphIR(
                value_defs=tuple(reversed(definitions)),
                operations=(right, left),
            )
        )

    assert _problem_codes(caught.value) == ["semantic_operation_cycle"]
    assert caught.value.problems[0].message.endswith("left, right")


def test_operation_outputs_and_value_producers_must_be_reciprocal() -> None:
    operation_id = _operation_id("produce")
    missing = operation_result_id(operation_id, "declared")
    orphan = operation_result_id(operation_id, "orphan")
    operation = SemanticOperation(
        id=operation_id,
        contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
        inputs=(),
        outputs=(("declared", missing),),
    )
    orphan_definition = ValueDef(
        id=orphan,
        value_type=FLOAT,
        availability=EXECUTE_POINT,
        source=OperationOutputSource(operation_id, "orphan"),
    )

    with pytest.raises(CheckFailed) as caught:
        verify_semantic_graph(
            SemanticGraphIR(
                value_defs=(orphan_definition,),
                operations=(operation,),
            )
        )

    assert _problem_codes(caught.value) == [
        "semantic_operation_output_missing_definition",
        "semantic_value_producer_missing_output",
    ]


def test_operation_output_definition_must_point_back_to_its_port() -> None:
    operation_id = _operation_id("produce")
    result_id = operation_result_id(operation_id)
    operation = SemanticOperation(
        id=operation_id,
        contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
        inputs=(),
        outputs=(("result", result_id),),
    )
    unrelated_definition = ValueDef(
        id=result_id,
        value_type=FLOAT,
        availability=PLAN_RUN,
        source=_plan_source(as_scalar_expr(1.0), expected_type=FLOAT),
    )

    with pytest.raises(CheckFailed) as caught:
        verify_semantic_graph(
            SemanticGraphIR(
                value_defs=(unrelated_definition,),
                operations=(operation,),
            )
        )

    assert _problem_codes(caught.value) == ["semantic_operation_output_source_mismatch"]


def test_opaque_operation_requires_one_execute_point_result() -> None:
    operation_id = _operation_id("opaque")
    output_id = operation_result_id(operation_id, "other")
    operation = SemanticOperation(
        id=operation_id,
        contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
        inputs=(),
        outputs=(("other", output_id),),
    )
    output = ValueDef(
        id=output_id,
        value_type=FLOAT,
        availability=PLAN_RUN,
        source=OperationOutputSource(operation_id, "other"),
    )

    with pytest.raises(CheckFailed) as caught:
        verify_semantic_graph(
            SemanticGraphIR(value_defs=(output,), operations=(operation,))
        )

    assert _problem_codes(caught.value) == ["semantic_opaque_operation_shape_invalid"]


def test_opaque_operation_rejects_plan_available_result() -> None:
    operation, result = _opaque_operation("opaque")
    plan_result = ValueDef(
        id=result.id,
        value_type=result.value_type,
        availability=PLAN_RUN,
        source=result.source,
    )

    with pytest.raises(CheckFailed) as caught:
        verify_semantic_graph(
            SemanticGraphIR(value_defs=(plan_result,), operations=(operation,))
        )

    assert _problem_codes(caught.value) == [
        "semantic_opaque_operation_availability_invalid"
    ]


def test_plan_expression_source_defensively_retains_semantics() -> None:
    expression = as_scalar_expr(1.0)
    assert isinstance(expression, LiteralScalarExpr)
    source = _plan_source(expression, expected_type=FLOAT)

    expression.value = 2.0
    projected = source.expression
    assert isinstance(projected, LiteralScalarExpr)
    projected.value = 3.0

    retained = source.expression
    assert isinstance(retained, LiteralScalarExpr)
    assert retained.value == 1.0


def test_plan_expression_source_derives_inputs_and_retains_value_equality() -> None:
    expression = input_ref("gain")
    source = _plan_source(
        expression,
        expected_type=FLOAT,
        bindings=RelationTypeBindings(inputs={"gain": FLOAT}),
    )
    same = _plan_source(
        input_ref("gain"),
        expected_type=FLOAT,
        bindings=RelationTypeBindings(inputs={"gain": FLOAT}),
    )
    different = _plan_source(
        input_ref("offset"),
        expected_type=FLOAT,
        bindings=RelationTypeBindings(inputs={"offset": FLOAT}),
    )

    expression.name = "mutated"

    assert source.source_inputs == ("gain",)
    assert source == same
    assert source != different
    assert source.imports == source.verified_plan.imports


def test_plan_expression_source_equality_includes_typed_import_signature() -> None:
    broad = _plan_source(
        input_ref("gain"),
        expected_type=FLOAT,
        bindings=RelationTypeBindings(inputs={"gain": FLOAT}),
    )
    bounded = _plan_source(
        input_ref("gain"),
        expected_type=FLOAT,
        bindings=RelationTypeBindings(
            inputs={"gain": Scalar(Float(minimum=0.0, maximum=1.0))}
        ),
    )

    assert broad != bounded


def test_semantic_graph_rejects_conflicting_types_for_one_input_import() -> None:
    integer = Scalar(Int())
    definitions = (
        ValueDef(
            id=_value_id("float-use"),
            value_type=FLOAT,
            availability=PLAN_RUN,
            source=_plan_source(
                input_ref("shared"),
                expected_type=FLOAT,
                bindings=RelationTypeBindings(inputs={"shared": FLOAT}),
            ),
        ),
        ValueDef(
            id=_value_id("int-use"),
            value_type=integer,
            availability=PLAN_RUN,
            source=_plan_source(
                input_ref("shared"),
                expected_type=integer,
                bindings=RelationTypeBindings(inputs={"shared": integer}),
            ),
        ),
    )

    with pytest.raises(CheckFailed) as caught:
        verify_semantic_graph(SemanticGraphIR(value_defs=definitions))

    assert _problem_codes(caught.value) == ["semantic_plan_import_type_conflict"]


def test_semantic_graph_rejects_conflicting_point_column_types() -> None:
    integer = Scalar(Int())
    definitions = (
        ValueDef(
            id=_value_id("float-point"),
            value_type=FLOAT,
            availability=PLAN_POINT,
            source=_plan_source(
                point_col("shared"),
                expected_type=FLOAT,
                bindings=RelationTypeBindings(
                    point_row=RowType((TableColumn("shared", FLOAT),))
                ),
            ),
        ),
        ValueDef(
            id=_value_id("int-point"),
            value_type=integer,
            availability=PLAN_POINT,
            source=_plan_source(
                point_col("shared"),
                expected_type=integer,
                bindings=RelationTypeBindings(
                    point_row=RowType((TableColumn("shared", integer),))
                ),
            ),
        ),
    )

    with pytest.raises(CheckFailed) as caught:
        verify_semantic_graph(SemanticGraphIR(value_defs=definitions))

    assert _problem_codes(caught.value) == ["semantic_point_row_type_conflict"]


def test_point_cross_internal_point_reference_does_not_raise_value_rate() -> None:
    integer = Scalar(Int())
    expected = Table(
        columns=(TableColumn("axis", integer), TableColumn("copy", integer)),
        min_rows=1,
        max_rows=1,
    )
    expression = literal_rows([{"axis": 1}]).point_cross(grid(copy=point_col("axis")))
    definition = ValueDef(
        id=_value_id("internal-point"),
        value_type=expected,
        availability=PLAN_RUN,
        source=_plan_source(
            expression,
            expected_type=expected,
            bindings=RelationTypeBindings(
                point_row=RowType((TableColumn("unrelated", FLOAT),))
            ),
        ),
    )

    verified = verify_semantic_graph(SemanticGraphIR(value_defs=(definition,)))

    assert verified.value_defs[definition.id].availability == PLAN_RUN


def test_literal_source_captures_and_projects_by_value() -> None:
    literal = {"nested": [1]}
    source = LiteralValueSource(literal)

    literal["nested"].append(2)
    projected = cast("dict[str, list[int]]", source.value)
    projected["nested"].append(3)

    assert source.value == {"nested": [1]}


def test_literal_source_preserves_opaque_payload_identity_without_deepcopy() -> None:
    class Undeepcopyable:
        def __deepcopy__(self, _memo: object) -> object:
            raise AssertionError("opaque payload body must not be deep-copied")

    body = Undeepcopyable()
    original = PayloadValue(schema_id="program", payload=body)
    source = LiteralValueSource(original)

    original.schema_id = "mutated"
    projected = cast("PayloadValue", source.value)
    projected.schema_id = "projected"

    retained = cast("PayloadValue", source.value)
    assert retained.schema_id == "program"
    assert retained.payload is body

    definition = ValueDef(
        id=_value_id("payload"),
        value_type=Scalar(Payload("program", python_type=Undeepcopyable)),
        availability=PLAN_RUN,
        source=source,
    )
    verify_semantic_graph(SemanticGraphIR(value_defs=(definition,)))


@pytest.mark.parametrize(
    ("value", "value_type"),
    [
        (None, FLOAT),
        (True, Scalar(Int())),
        (1, BOOL),
    ],
)
def test_literal_source_value_must_match_declared_scalar_type(
    value: object,
    value_type: ValueType,
) -> None:
    definition = ValueDef(
        id=_value_id("literal"),
        value_type=value_type,
        availability=PLAN_RUN,
        source=LiteralValueSource(value),
    )

    with pytest.raises(CheckFailed) as caught:
        verify_semantic_graph(SemanticGraphIR(value_defs=(definition,)))

    assert _problem_codes(caught.value) == ["semantic_literal_value_type_mismatch"]


@pytest.mark.parametrize(
    ("value", "value_type"),
    [
        (None, Scalar(Float(), nullable=True)),
        (True, BOOL),
        (1, Scalar(Int())),
        (1, FLOAT),
    ],
)
def test_literal_source_accepts_values_in_declared_scalar_domain(
    value: object,
    value_type: ValueType,
) -> None:
    definition = ValueDef(
        id=_value_id("literal"),
        value_type=value_type,
        availability=PLAN_RUN,
        source=LiteralValueSource(value),
    )

    verified = verify_semantic_graph(SemanticGraphIR(value_defs=(definition,)))

    assert verified.value_defs[definition.id] == definition


def test_plan_literal_and_route_sources_require_canonical_availability() -> None:
    definitions = (
        ValueDef(
            id=_value_id("plan"),
            value_type=FLOAT,
            availability=EXECUTE_POINT,
            source=_plan_source(as_scalar_expr(1.0), expected_type=FLOAT),
        ),
        ValueDef(
            id=_value_id("literal"),
            value_type=Scalar(Int()),
            availability=EXECUTE_POINT,
            source=LiteralValueSource(1),
        ),
        ValueDef(
            id=_value_id("route"),
            value_type=Route(),
            availability=PLAN_RUN,
            source=RouteValueSource(LogicalResourcePortId(SymbolId(local_id="port"))),
        ),
    )

    with pytest.raises(CheckFailed) as caught:
        verify_semantic_graph(SemanticGraphIR(value_defs=definitions))

    assert _problem_codes(caught.value) == [
        "semantic_literal_availability_invalid",
        "semantic_plan_expression_availability_invalid",
        "semantic_route_availability_invalid",
    ]


def test_plan_expression_accepts_explicit_run_and_point_rates_at_plan_stage() -> None:
    point_row = RowType(columns=(TableColumn("frequency", FLOAT),))
    point = ValueDef(
        id=_value_id("point"),
        value_type=FLOAT,
        availability=PLAN_POINT,
        source=_plan_source(
            point_col("frequency"),
            expected_type=FLOAT,
            bindings=RelationTypeBindings(point_row=point_row),
        ),
    )
    run = _plan_value("run")

    verified = verify_semantic_graph(SemanticGraphIR(value_defs=(point, run)))

    assert verified.value_defs[point.id] == point
    assert verified.value_defs[run.id] == run

    wrong_stage = replace(point, availability=EXECUTE_POINT)
    with pytest.raises(CheckFailed) as caught:
        verify_semantic_graph(SemanticGraphIR(value_defs=(wrong_stage,)))
    assert _problem_codes(caught.value) == [
        "semantic_plan_expression_availability_invalid"
    ]


def test_plan_expression_rate_must_match_point_and_row_references() -> None:
    row_scope = RowScopeId(SymbolId(local_id="row"))
    region_id = state_each_region_id(row_scope)
    row_type = Table(columns=(TableColumn("frequency", FLOAT),))
    row_signature = RowType.from_table(row_type)
    relation = _plan_value("rows", value_type=row_type)
    point = ValueDef(
        id=_value_id("point-at-run-rate"),
        value_type=FLOAT,
        availability=PLAN_RUN,
        source=_plan_source(
            point_col("frequency"),
            expected_type=FLOAT,
            bindings=RelationTypeBindings(point_row=row_signature),
        ),
    )
    row = ValueDef(
        id=_value_id("row-at-run-rate"),
        value_type=FLOAT,
        availability=PLAN_RUN,
        source=_plan_source(
            col("frequency", row_scope_id=row_scope),
            expected_type=FLOAT,
            bindings=RelationTypeBindings(row_arguments={row_scope: row_signature}),
        ),
        owner_region_id=region_id,
    )
    definitions = (
        point,
        relation,
        row,
    )
    region = StateEachRegion(
        id=region_id,
        row_argument=RowArgumentDef(row_scope, row_type),
        relation=ValueUse(relation.id),
        resource_port=LogicalResourcePortId(SymbolId(local_id="source")),
        capability_id="set_frequency",
        field_path="frequency",
        value=ValueUse(row.id),
    )

    with pytest.raises(CheckFailed) as caught:
        verify_semantic_graph(
            SemanticGraphIR(value_defs=definitions, row_regions=(region,))
        )

    assert _problem_codes(caught.value) == [
        "semantic_plan_expression_rate_mismatch",
        "semantic_plan_expression_rate_mismatch",
    ]


def test_row_region_relation_is_evaluated_before_its_own_binder() -> None:
    row_scope = RowScopeId(SymbolId(local_id="row"))
    region_id = state_each_region_id(row_scope)
    row_type = Table(columns=())
    relation = replace(
        _plan_value("rows", value_type=row_type),
        owner_region_id=region_id,
    )
    value = _plan_value("value")
    region = StateEachRegion(
        id=region_id,
        row_argument=RowArgumentDef(row_scope, row_type),
        relation=ValueUse(relation.id),
        resource_port=LogicalResourcePortId(SymbolId(local_id="source")),
        capability_id="set_frequency",
        field_path="frequency",
        value=ValueUse(value.id),
    )

    with pytest.raises(CheckFailed) as caught:
        verify_semantic_graph(
            SemanticGraphIR(
                value_defs=(relation, value),
                row_regions=(region,),
            )
        )

    assert _problem_codes(caught.value) == [
        "semantic_row_region_relation_visibility_invalid"
    ]


def test_row_region_binder_collision_is_rejected_before_graph_construction() -> None:
    row_scope = RowScopeId(SymbolId(local_id="row"))
    row_type = Table(columns=())
    with pytest.raises(RelationPlanVerificationError) as caught:
        verify_relation_plan(
            literal_rows([])
            .filter(
                col("keep", row_scope_id=row_scope),
                row_scope_id=row_scope,
            )
            .column("entity"),
            bindings=RelationTypeBindings(
                row_arguments={row_scope: RowType.from_table(row_type)}
            ),
        )

    assert caught.value.code == "row_binder_collision"


def test_scalar_binary_infers_result_type_and_combines_availability() -> None:
    graph = _binary_graph()

    verified = verify_semantic_graph(graph)

    result_id = operation_result_id(_operation_id("add"))
    assert verified.value_defs[result_id].value_type == FLOAT
    assert verified.value_defs[result_id].availability == PLAN_RUN


def test_scalar_binary_requires_portable_semantics() -> None:
    graph = _binary_graph()
    operation = replace(
        graph.operations[0],
        contract=replace(
            graph.operations[0].contract,
            portability=Portability.IMPLEMENTATION_DEFINED,
            placement=PlacementConstraint.HOST,
        ),
    )

    with pytest.raises(CheckFailed) as caught:
        verify_semantic_graph(replace(graph, operations=(operation,)))

    assert _problem_codes(caught.value) == [
        "semantic_scalar_binary_portability_invalid"
    ]


def test_scalar_binary_allows_host_placement_constraint() -> None:
    graph = _binary_graph()
    operation = replace(
        graph.operations[0],
        contract=replace(
            graph.operations[0].contract,
            placement=PlacementConstraint.HOST,
        ),
    )

    verified = verify_semantic_graph(replace(graph, operations=(operation,)))

    assert verified.graph.operations[0].contract.placement is PlacementConstraint.HOST


def test_scalar_binary_requires_scalar_inputs() -> None:
    graph = _binary_graph(left_type=Table(columns=()))

    with pytest.raises(CheckFailed) as caught:
        verify_semantic_graph(graph)

    assert _problem_codes(caught.value) == ["semantic_scalar_binary_input_type_invalid"]


def test_scalar_binary_requires_left_and_right_inputs() -> None:
    graph = _binary_graph()
    operation = replace(
        graph.operations[0],
        inputs=(("value", graph.operations[0].inputs[0][1]),),
    )

    with pytest.raises(CheckFailed) as caught:
        verify_semantic_graph(replace(graph, operations=(operation,)))

    assert _problem_codes(caught.value) == ["semantic_scalar_binary_shape_invalid"]


def test_scalar_binary_collects_result_type_and_availability_mismatches() -> None:
    graph = _binary_graph(
        result_type=BOOL,
        result_availability=EXECUTE_POINT,
    )

    with pytest.raises(CheckFailed) as caught:
        verify_semantic_graph(graph)

    assert _problem_codes(caught.value) == [
        "semantic_scalar_binary_result_type_mismatch",
        "semantic_scalar_binary_availability_mismatch",
    ]


def test_scalar_binary_preserves_null_literal_type_inference() -> None:
    left = _plan_value("left")
    null = ValueDef(
        id=_value_id("null"),
        value_type=Scalar(Float(), nullable=True),
        availability=PLAN_RUN,
        source=LiteralValueSource(None),
    )
    operation_id = _operation_id("equals-null")
    result_id = operation_result_id(operation_id)
    operation = SemanticOperation(
        id=operation_id,
        contract=scalar_binary_operation_contract("=="),
        inputs=(("left", ValueUse(left.id)), ("right", ValueUse(null.id))),
        outputs=(("result", result_id),),
    )
    result = ValueDef(
        id=result_id,
        value_type=BOOL,
        availability=PLAN_RUN,
        source=OperationOutputSource(operation_id),
    )

    verified = verify_semantic_graph(
        SemanticGraphIR(
            value_defs=(left, null, result),
            operations=(operation,),
        )
    )

    assert verified.value_defs[result_id].value_type == BOOL


def test_implementation_catalog_rejects_duplicate_implementation_ids() -> None:
    first, first_result = _opaque_operation("first")
    second, second_result = _opaque_operation("second")
    graph = SemanticGraphIR(
        value_defs=(first_result, second_result),
        operations=(first, second),
    )
    implementation_id = ImplementationId("shared")
    catalog = ImplementationCatalog(
        local_python=(
            LocalPythonImplementation(
                implementation_id,
                first.id,
                first.contract,
                lambda: 1,
            ),
            LocalPythonImplementation(
                implementation_id,
                second.id,
                second.contract,
                lambda: 2,
            ),
        )
    )

    with pytest.raises(CheckFailed) as caught:
        verify_implementation_catalog(graph, catalog)

    assert _problem_codes(caught.value) == ["semantic_implementation_duplicate"]


def test_implementation_catalog_rejects_orphan_implementations() -> None:
    unknown = _operation_id("unknown")
    catalog = ImplementationCatalog(
        local_python=(
            LocalPythonImplementation(
                ImplementationId("orphan"),
                unknown,
                LOCAL_OPAQUE_OPERATION_CONTRACT,
                lambda: None,
            ),
        )
    )

    with pytest.raises(CheckFailed) as caught:
        verify_implementation_catalog(SemanticGraphIR(), catalog)

    assert _problem_codes(caught.value) == ["semantic_implementation_orphan"]


def test_implementation_catalog_rejects_mismatched_declared_contract() -> None:
    operation, result = _opaque_operation("compute")
    graph = SemanticGraphIR(value_defs=(result,), operations=(operation,))
    catalog = ImplementationCatalog(
        local_python=(
            LocalPythonImplementation(
                ImplementationId("wrong-contract"),
                operation.id,
                scalar_binary_operation_contract("+"),
                lambda: 1,
            ),
        )
    )

    with pytest.raises(CheckFailed) as caught:
        verify_implementation_catalog(graph, catalog)

    assert _problem_codes(caught.value) == ["semantic_implementation_contract_mismatch"]


def test_implementation_catalog_preserves_unselected_target_candidates() -> None:
    operation, result = _opaque_operation("compute")
    graph = SemanticGraphIR(value_defs=(result,), operations=(operation,))
    catalog = ImplementationCatalog(
        local_python=(
            LocalPythonImplementation(
                ImplementationId("first"),
                operation.id,
                operation.contract,
                lambda: 1,
            ),
            LocalPythonImplementation(
                ImplementationId("second"),
                operation.id,
                operation.contract,
                lambda: 2,
            ),
        )
    )

    verified = verify_implementation_catalog(graph, catalog)

    assert tuple(item.id.value for item in verified.local_python) == (
        "first",
        "second",
    )


def test_implementation_catalog_does_not_select_target_coverage() -> None:
    operation, result = _opaque_operation("compute")
    opaque = SemanticGraphIR(value_defs=(result,), operations=(operation,))

    assert verify_implementation_catalog(opaque, ImplementationCatalog()) == (
        ImplementationCatalog()
    )
    assert (
        verify_implementation_catalog(
            _binary_graph(),
            ImplementationCatalog(),
        )
        == ImplementationCatalog()
    )


def test_callable_and_source_sidecars_do_not_participate_in_graph_equality() -> None:
    operation, result = _opaque_operation("compute")
    graph = SemanticGraphIR(value_defs=(result,), operations=(operation,))
    implementation_id = ImplementationId("compute.local")
    first_catalog = ImplementationCatalog(
        local_python=(
            LocalPythonImplementation(
                implementation_id,
                operation.id,
                operation.contract,
                lambda: 1,
            ),
        )
    )
    second_catalog = ImplementationCatalog(
        local_python=(
            LocalPythonImplementation(
                implementation_id,
                operation.id,
                operation.contract,
                lambda: 2,
            ),
        )
    )
    first_sources = SourceMap(
        operation_sources=(
            (
                operation.id,
                SourceAnchor("compute", "first", composition_scope=("left",)),
            ),
        )
    )
    second_sources = SourceMap(
        operation_sources=(
            (
                operation.id,
                SourceAnchor("compute", "second", composition_scope=("right",)),
            ),
        )
    )

    assert first_catalog == second_catalog
    assert first_sources != second_sources
    assert graph == SemanticGraphIR(value_defs=(result,), operations=(operation,))


def test_source_map_requires_exact_declaration_coverage() -> None:
    operation, result = _opaque_operation("compute")
    graph = SemanticGraphIR(value_defs=(result,), operations=(operation,))
    operation_anchor = SourceAnchor("compute", "operation")

    with pytest.raises(CheckFailed) as caught:
        verify_source_map(
            graph,
            SourceMap(operation_sources=((operation.id, operation_anchor),)),
        )

    assert _problem_codes(caught.value) == ["semantic_source_map_value_missing"]

    source_map = verify_source_map(
        graph,
        SourceMap(
            operation_sources=((operation.id, operation_anchor),),
            value_sources=((result.id, SourceAnchor("compute_result", "value")),),
        ),
    )
    assert dict(source_map.operation_sources)[operation.id] == operation_anchor
