from __future__ import annotations

from dataclasses import replace
from typing import cast

import pytest

from scopecat.compiler.relations.verification import (
    RelationPlanVerificationError,
    RelationTypeBindings,
    RowType,
    verify_relation_plan,
)
from scopecat.compiler.semantic.dependencies import (
    analyze_residual_dependencies,
)
from scopecat.compiler.semantic.model import (
    LiteralValueSource,
    PlanExpressionSource,
    SemanticGraphIR,
    SemanticOperation,
    ValueDef,
    ValueUse,
)
from scopecat.compiler.semantic.operation_contract import (
    LOCAL_OPAQUE_OPERATION_CONTRACT,
    scalar_binary_operation_contract,
)
from scopecat.compiler.semantic.verification import (
    verify_semantic_graph,
)
from scopecat.graph.relations.model import (
    LiteralScalarExpr,
    RelationExpr,
    RowScopeId,
    ScalarExpr,
    SeriesExpr,
    as_scalar_expr,
    col,
    input_ref,
    literal_rows,
    point_col,
)
from scopecat.graph.values import (
    OperationId,
    ValueId,
    operation_result_id,
)
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.payloads import PayloadValue
from scopecat.kernel.problems import ModelLocation
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import (
    Bool,
    Float,
    Int,
    Payload,
    Scalar,
    Table,
    TableColumn,
    ValueType,
)

FLOAT = Scalar(Float())
BOOL = Scalar(Bool())


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
) -> ValueDef:
    expression = (
        literal_rows([]) if isinstance(value_type, Table) else as_scalar_expr(1.0)
    )
    return ValueDef(
        id=_value_id(local_id),
        value_type=value_type,
        source=_plan_source(expression, expected_type=value_type),
    )


def _opaque_operation(
    local_id: str,
    *,
    inputs: tuple[tuple[str, ValueUse], ...] = (),
) -> tuple[SemanticOperation, ValueId]:
    operation_id = _operation_id(local_id)
    result_id = operation_result_id(operation_id)
    return (
        SemanticOperation(
            id=operation_id,
            contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
            inputs=inputs,
            result_id=result_id,
            result_type=FLOAT,
        ),
        result_id,
    )


def _binary_graph(
    *,
    left_type: ValueType = FLOAT,
    right_type: ValueType = FLOAT,
    result_type: ValueType = FLOAT,
) -> SemanticGraphIR:
    left = _plan_value(
        "left",
        value_type=left_type,
    )
    right = _plan_value(
        "right",
        value_type=right_type,
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
        result_id=result_id,
        result_type=result_type,
    )
    return SemanticGraphIR(
        value_defs=(left, right),
        operations=(operation,),
    )


def _problem_codes(error: CheckFailed) -> list[str]:
    return [problem.code for problem in error.problems]


def test_residual_dependency_closure_includes_portable_downstream_operations() -> None:
    producer, produced_id = _opaque_operation("produce")
    literal = _plan_value("literal")
    operation_id = _operation_id("add")
    result_id = operation_result_id(operation_id)
    operation = SemanticOperation(
        id=operation_id,
        contract=scalar_binary_operation_contract("+"),
        inputs=(
            ("left", ValueUse(produced_id)),
            ("right", ValueUse(literal.id)),
        ),
        result_id=result_id,
        result_type=FLOAT,
    )
    operations = (producer, operation)
    residual = analyze_residual_dependencies(operations)

    assert residual.value_ids == frozenset({produced_id, result_id})
    assert residual.operation_ids == frozenset({producer.id, operation.id})


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
    producer, producer_result_id = _opaque_operation("producer")
    independent, _independent_result_id = _opaque_operation("independent")
    consumer, _consumer_result_id = _opaque_operation(
        "consumer",
        inputs=(("value", ValueUse(producer_result_id)),),
    )

    forward = verify_semantic_graph(
        SemanticGraphIR(
            operations=(consumer, independent, producer),
        )
    )
    reversed_declarations = verify_semantic_graph(
        SemanticGraphIR(
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
        result_id=result_id,
        result_type=FLOAT,
    )
    second = SemanticOperation(
        id=operation_id,
        contract=scalar_binary_operation_contract("+"),
        inputs=(),
        result_id=result_id,
        result_type=FLOAT,
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
    operation, _result_id = _opaque_operation(
        "consumer",
        inputs=(("missing", ValueUse(_value_id("missing"))),),
    )

    with pytest.raises(CheckFailed) as caught:
        verify_semantic_graph(SemanticGraphIR(operations=(operation,)))

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
        result_id=left_result,
        result_type=FLOAT,
    )
    right = SemanticOperation(
        id=right_id,
        contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
        inputs=(("left", ValueUse(left_result)),),
        result_id=right_result,
        result_type=FLOAT,
    )

    with pytest.raises(CheckFailed) as caught:
        verify_semantic_graph(
            SemanticGraphIR(
                operations=(right, left),
            )
        )

    assert _problem_codes(caught.value) == ["semantic_operation_cycle"]
    assert caught.value.problems[0].message.endswith("left, right")


def test_operation_result_cannot_shadow_a_plan_value() -> None:
    operation_id = _operation_id("produce")
    result_id = operation_result_id(operation_id)
    operation = SemanticOperation(
        id=operation_id,
        contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
        inputs=(),
        result_id=result_id,
        result_type=FLOAT,
    )
    plan_definition = ValueDef(
        id=result_id,
        value_type=FLOAT,
        source=_plan_source(as_scalar_expr(1.0), expected_type=FLOAT),
    )

    with pytest.raises(CheckFailed) as caught:
        verify_semantic_graph(
            SemanticGraphIR(
                value_defs=(plan_definition,),
                operations=(operation,),
            )
        )

    assert _problem_codes(caught.value) == ["semantic_value_definition_duplicate"]


def test_plan_expression_source_retains_semantics() -> None:
    expression = as_scalar_expr(1.0)
    assert isinstance(expression, LiteralScalarExpr)
    source = _plan_source(expression, expected_type=FLOAT)

    projected = source.expression
    assert isinstance(projected, LiteralScalarExpr)
    assert projected is not expression

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
            source=_plan_source(
                input_ref("shared"),
                expected_type=FLOAT,
                bindings=RelationTypeBindings(inputs={"shared": FLOAT}),
            ),
        ),
        ValueDef(
            id=_value_id("int-use"),
            value_type=integer,
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


def test_literal_source_captures_and_projects_by_value() -> None:
    literal = {"nested": [1]}
    source = LiteralValueSource(literal)

    literal["nested"].append(2)
    projected = cast("dict[str, list[int]]", source.value)
    projected["nested"].append(3)

    assert source.value == {"nested": [1]}


def test_literal_source_reuses_immutable_opaque_payload_without_deepcopy() -> None:
    class Undeepcopyable:
        def __deepcopy__(self, _memo: object) -> object:
            raise AssertionError("opaque payload body must not be deep-copied")

    body = Undeepcopyable()
    original = PayloadValue(schema_id="program", payload=body)
    source = LiteralValueSource(original)

    retained = cast("PayloadValue", source.value)
    assert retained is original
    assert retained.schema_id == "program"
    assert retained.payload is body

    definition = ValueDef(
        id=_value_id("payload"),
        value_type=Scalar(Payload("program", python_type=Undeepcopyable)),
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
        source=LiteralValueSource(value),
    )

    verified = verify_semantic_graph(SemanticGraphIR(value_defs=(definition,)))

    assert verified.value_defs[definition.id] == definition


def test_plan_expression_accepts_run_and_point_dependencies() -> None:
    point_row = RowType(columns=(TableColumn("frequency", FLOAT),))
    point = ValueDef(
        id=_value_id("point"),
        value_type=FLOAT,
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


def test_row_binder_collision_is_rejected_before_graph_construction() -> None:
    row_scope = RowScopeId(SymbolId(local_id="row"))
    row_type = Table(columns=())
    with pytest.raises(RelationPlanVerificationError) as caught:
        verify_relation_plan(
            literal_rows([]).with_columns(
                row_scope_id=row_scope,
                copied=col("keep", row_scope_id=row_scope),
            ),
            bindings=RelationTypeBindings(
                row_arguments={row_scope: RowType.from_table(row_type)}
            ),
        )

    assert caught.value.code == "row_binder_collision"


def test_scalar_binary_infers_result_type() -> None:
    graph = _binary_graph()

    verified = verify_semantic_graph(graph)

    result_id = operation_result_id(_operation_id("add"))
    assert verified.value_types[result_id] == FLOAT


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


def test_scalar_binary_reports_result_type_mismatch() -> None:
    graph = _binary_graph(result_type=BOOL)

    with pytest.raises(CheckFailed) as caught:
        verify_semantic_graph(graph)

    assert _problem_codes(caught.value) == [
        "semantic_scalar_binary_result_type_mismatch"
    ]


def test_scalar_binary_preserves_null_literal_type_inference() -> None:
    left = _plan_value("left")
    null = ValueDef(
        id=_value_id("null"),
        value_type=Scalar(Float(), nullable=True),
        source=LiteralValueSource(None),
    )
    operation_id = _operation_id("equals-null")
    result_id = operation_result_id(operation_id)
    operation = SemanticOperation(
        id=operation_id,
        contract=scalar_binary_operation_contract("=="),
        inputs=(("left", ValueUse(left.id)), ("right", ValueUse(null.id))),
        result_id=result_id,
        result_type=BOOL,
    )

    verified = verify_semantic_graph(
        SemanticGraphIR(
            value_defs=(left, null),
            operations=(operation,),
        )
    )

    assert verified.value_types[result_id] == BOOL
