from __future__ import annotations

from dataclasses import replace
from functools import partial
from typing import cast

import pytest
from hypothesis import given
from hypothesis import strategies as st

from scopecat._compiler.binding import bind_program, materialize_local_plan
from scopecat._compiler.environment import validate_config_environment
from scopecat._compiler.linked import link_program
from scopecat._compiler.point_domain import PointDomain
from scopecat._compiler.program import (
    TypedComputeNode,
    TypedComputeOutput,
    TypedProgram,
    ValueInput,
)
from scopecat._compiler.verification import verify_typed_program
from scopecat._execution.lowering import build_execution_program
from scopecat._execution.program import ComputeStage
from scopecat._operation_contract import (
    LOCAL_OPAQUE_OPERATION_CONTRACT,
    EffectClass,
    OpaqueSemantics,
    OperationContract,
    OperationSemantics,
    PlacementConstraint,
    Portability,
    ScalarBinarySemantics,
    operation_contract_issues,
    scalar_binary_operation_contract,
)
from scopecat._point_domain_algebra import point_rows
from scopecat._relation_analysis import RelationOperation
from scopecat._relation_backend import (
    PreparedRelationEvaluation,
    ReferenceRelationBackend,
)
from scopecat._relation_scalar_eval import eval_binary
from scopecat._relation_verification import RelationTypeBindings
from scopecat._relations import RelationExpr, Row, lit, literal_rows
from scopecat._scalar_operators import SCALAR_OPERATORS, ScalarOperator
from scopecat._semantic_graph import (
    ImplementationCatalog,
    ImplementationId,
    LiteralValueSource,
    LocalPythonImplementation,
    OperationId,
    OperationOutputSource,
    SemanticGraphIR,
    SemanticOperation,
    ValueDef,
    ValueId,
    ValueUse,
    operation_result_id,
    verify_implementation_catalog,
    verify_semantic_graph,
)
from scopecat._symbols import SymbolId
from scopecat._value_availability import ValueAvailability, ValueRate, ValueStage
from scopecat.authoring._assembly_lowering import lower_semantic_compute_graph
from scopecat.errors import CheckFailed
from scopecat.value_types import Float, Scalar, Table
from tests.support.authoring import load_config
from tests.support.relation_plans import table_value_expr, value_expr

_FLOAT = Scalar(Float())
_PLAN_RUN = ValueAvailability(ValueStage.PLAN, ValueRate.RUN)
_EXECUTE_POINT = ValueAvailability(ValueStage.EXECUTE, ValueRate.POINT)


class _TrackingBackend(ReferenceRelationBackend):
    materialization_count: int

    def __init__(self) -> None:
        super().__init__(backend_id="tests.operation-contract")
        object.__setattr__(self, "materialization_count", 0)

    def materialize_relation(
        self,
        evaluation: PreparedRelationEvaluation[RelationExpr],
    ) -> list[Row]:
        object.__setattr__(
            self,
            "materialization_count",
            self.materialization_count + 1,
        )
        return super().materialize_relation(evaluation)


@given(
    semantics=st.sampled_from(
        (
            OpaqueSemantics(),
            *(ScalarBinarySemantics(operator) for operator in SCALAR_OPERATORS),
        )
    ),
    effect=st.sampled_from(tuple(EffectClass)),
    portability=st.sampled_from(tuple(Portability)),
    placement=st.sampled_from(tuple(PlacementConstraint)),
)
def test_operation_contract_fact_matrix_is_exhaustive(
    semantics: OperationSemantics,
    effect: EffectClass,
    portability: Portability,
    placement: PlacementConstraint,
) -> None:
    contract = OperationContract(
        semantics=semantics,
        effect=effect,
        portability=portability,
        placement=placement,
    )

    valid = not operation_contract_issues(contract)
    expected = (
        effect is EffectClass.PURE
        and isinstance(semantics, OpaqueSemantics)
        and portability is Portability.IMPLEMENTATION_DEFINED
    ) or (
        effect is EffectClass.PURE
        and isinstance(semantics, ScalarBinarySemantics)
        and portability is Portability.PORTABLE
    )

    assert valid is expected


def test_operation_contract_rejects_unknown_orthogonal_facts() -> None:
    contract = OperationContract(
        semantics=cast("OperationSemantics", object()),
        effect=cast("EffectClass", "future-effect"),
        portability=cast("Portability", "future-portability"),
        placement=cast("PlacementConstraint", "future-placement"),
    )

    assert {issue.code for issue in operation_contract_issues(contract)} == {
        "semantic_operation_effect_unknown",
        "semantic_operation_placement_unknown",
        "semantic_operation_portability_unknown",
        "semantic_operation_semantics_unknown",
    }


@pytest.mark.parametrize("operator", ["**", []], ids=("unknown", "unhashable"))
def test_operation_contract_rejects_unknown_scalar_operator(
    operator: object,
) -> None:
    contract = replace(
        scalar_binary_operation_contract("+"),
        semantics=ScalarBinarySemantics(cast("ScalarOperator", operator)),
    )

    assert [issue.code for issue in operation_contract_issues(contract)] == [
        "semantic_scalar_binary_operator_invalid"
    ]


def test_semantic_verification_reports_unknown_contract_before_lowering() -> None:
    operation_id = OperationId(SymbolId(local_id="unknown"))
    output_id = operation_result_id(operation_id)
    operation = SemanticOperation(
        id=operation_id,
        contract=replace(
            LOCAL_OPAQUE_OPERATION_CONTRACT,
            semantics=cast("OperationSemantics", object()),
        ),
        inputs=(),
        outputs=(("result", output_id),),
    )
    output = ValueDef(
        id=output_id,
        value_type=_FLOAT,
        availability=_EXECUTE_POINT,
        source=OperationOutputSource(operation_id),
    )

    with pytest.raises(CheckFailed) as caught:
        verify_semantic_graph(
            SemanticGraphIR(value_defs=(output,), operations=(operation,))
        )

    assert [problem.code for problem in caught.value.problems] == [
        "semantic_operation_semantics_unknown"
    ]


def test_semantic_verification_does_not_reclassify_invalid_operator() -> None:
    operation_id = OperationId(SymbolId(local_id="invalid-operator"))
    left_id = ValueId(SymbolId(local_id="left"))
    right_id = ValueId(SymbolId(local_id="right"))
    output_id = operation_result_id(operation_id)
    operation = SemanticOperation(
        id=operation_id,
        contract=replace(
            scalar_binary_operation_contract("+"),
            semantics=ScalarBinarySemantics(cast("ScalarOperator", "**")),
        ),
        inputs=(
            ("left", ValueUse(left_id)),
            ("right", ValueUse(right_id)),
        ),
        outputs=(("result", output_id),),
    )
    graph = SemanticGraphIR(
        value_defs=(
            ValueDef(
                id=left_id,
                value_type=_FLOAT,
                availability=_PLAN_RUN,
                source=LiteralValueSource(1.0),
            ),
            ValueDef(
                id=right_id,
                value_type=_FLOAT,
                availability=_PLAN_RUN,
                source=LiteralValueSource(2.0),
            ),
            ValueDef(
                id=output_id,
                value_type=_FLOAT,
                availability=_PLAN_RUN,
                source=OperationOutputSource(operation_id),
            ),
        ),
        operations=(operation,),
    )

    with pytest.raises(CheckFailed) as caught:
        verify_semantic_graph(graph)

    assert [problem.code for problem in caught.value.problems] == [
        "semantic_scalar_binary_operator_invalid"
    ]


def test_typed_program_rechecks_scalar_contract_shape() -> None:
    operation_id = OperationId(SymbolId(local_id="malformed-scalar"))
    node = TypedComputeNode(
        id=operation_id,
        contract=scalar_binary_operation_contract("+"),
        inputs={"value": ValueInput(value=value_expr(lit(1.0), expected_type=_FLOAT))},
        result=TypedComputeOutput(
            id=operation_result_id(operation_id),
            value_type=_FLOAT,
            availability=_EXECUTE_POINT,
        ),
    )
    program = TypedProgram(
        id="malformed-scalar-contract",
        kind="compiler_test",
        point_domain=_point_domain(),
        compute_nodes=(node,),
    )

    with pytest.raises(CheckFailed) as caught:
        verify_typed_program(program)

    assert [problem.code for problem in caught.value.problems] == [
        "semantic_scalar_binary_shape_invalid"
    ]


def test_contract_survives_every_local_compiler_boundary() -> None:
    graph, program = _compute_program("*")
    environment = validate_config_environment(load_config())

    linked = link_program(program, environment)
    bound = materialize_local_plan(linked)
    execution = build_execution_program(bound)

    assert bound.valid, bound.problems
    semantic_contracts = {
        operation.id: operation.contract for operation in graph.operations
    }
    assert {
        node.id: node.contract for node in program.compute_nodes
    } == semantic_contracts
    assert {
        node.id: node.contract for node in linked.program.compute_nodes
    } == semantic_contracts
    assert {
        call.operation_id: call.contract for call in bound.points[0].compute
    } == semantic_contracts
    stage = execution.points[0].stages[0]
    assert isinstance(stage, ComputeStage)
    assert {
        operation.semantic_operation_id: operation.contract
        for operation in stage.operations
    } == {
        operation_id.qualified_name: contract
        for operation_id, contract in semantic_contracts.items()
    }


def test_local_target_selection_aggregates_failures_before_materialization() -> None:
    _graph, program = _compute_program("+", include_scalar_implementation=False)
    environment = validate_config_environment(load_config())
    backend = _TrackingBackend()
    object.__setattr__(
        backend,
        "supported_operations",
        backend.supported_operations - {RelationOperation.SCALAR_LITERAL},
    )

    linked = link_program(program, environment)
    plan = materialize_local_plan(linked, relation_backend=backend)

    assert not plan.valid
    assert plan.points == ()
    assert {problem.code for problem in plan.problems} == {
        "semantic_operation_implementation_missing",
        "relation_backend_capability_unsupported",
    }
    assert backend.materialization_count == 0


def test_compute_cache_identity_includes_semantic_contract() -> None:
    _add_graph, add_program = _compute_program("+")
    _multiply_graph, multiply_program = _compute_program("*")
    environment = validate_config_environment(load_config())

    add = bind_program(add_program, environment)
    multiply = bind_program(multiply_program, environment)

    add_call = add.points[0].compute[-1]
    multiply_call = multiply.points[0].compute[-1]
    assert add_call.operation_id == multiply_call.operation_id
    assert add_call.implementation_id == multiply_call.implementation_id
    assert add_call.inputs == multiply_call.inputs
    assert add_call.contract != multiply_call.contract
    assert add_call.cache_key != multiply_call.cache_key


def _compute_program(
    operator: ScalarOperator,
    *,
    include_scalar_implementation: bool = True,
) -> tuple[SemanticGraphIR, TypedProgram]:
    producer_id = OperationId(SymbolId(local_id="produce"))
    scalar_id = OperationId(SymbolId(local_id="combine"))
    producer_output_id = operation_result_id(producer_id)
    scalar_output_id = operation_result_id(scalar_id)
    literal_id = ValueId(SymbolId(local_id="literal"))
    producer = SemanticOperation(
        id=producer_id,
        contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
        inputs=(),
        outputs=(("result", producer_output_id),),
    )
    scalar = SemanticOperation(
        id=scalar_id,
        contract=scalar_binary_operation_contract(operator),
        inputs=(
            ("left", ValueUse(producer_output_id)),
            ("right", ValueUse(literal_id)),
        ),
        outputs=(("result", scalar_output_id),),
    )
    graph = SemanticGraphIR(
        value_defs=(
            ValueDef(
                id=producer_output_id,
                value_type=_FLOAT,
                availability=_EXECUTE_POINT,
                source=OperationOutputSource(producer_id),
            ),
            ValueDef(
                id=literal_id,
                value_type=_FLOAT,
                availability=_PLAN_RUN,
                source=LiteralValueSource(2.0),
            ),
            ValueDef(
                id=scalar_output_id,
                value_type=_FLOAT,
                availability=_EXECUTE_POINT,
                source=OperationOutputSource(scalar_id),
            ),
        ),
        operations=(scalar, producer),
    )
    verified = verify_semantic_graph(graph)
    implementations = [
        LocalPythonImplementation(
            ImplementationId("python.produce.v1"),
            producer_id,
            producer.contract,
            lambda: 3.0,
        )
    ]
    if include_scalar_implementation:
        implementations.append(
            LocalPythonImplementation(
                ImplementationId("python.combine.v1"),
                scalar_id,
                scalar.contract,
                partial(eval_binary, operator),
            )
        )
    catalog = verify_implementation_catalog(
        verified.graph,
        ImplementationCatalog(local_python=tuple(implementations)),
    )
    nodes, selected_catalog = lower_semantic_compute_graph(
        verified,
        catalog,
        {},
        type_bindings=RelationTypeBindings(),
    )
    program = TypedProgram(
        id="operation-contract-program",
        kind="compiler_test",
        point_domain=_point_domain(),
        compute_nodes=nodes,
        implementation_catalog=selected_catalog,
    )
    return verified.graph, program


def _point_domain() -> PointDomain:
    return PointDomain(
        root=point_rows(
            table_value_expr(
                literal_rows([{}]),
                expected_type=Table(columns=(), min_rows=1, max_rows=1),
            )
        )
    )
