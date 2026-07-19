from __future__ import annotations

from functools import partial

import pytest
from hypothesis import given
from hypothesis import strategies as st

from scopecat.compiler.frontend.assembly_lowering import lower_semantic_compute_graph
from scopecat.compiler.frontend.environment import validate_config_environment
from scopecat.compiler.relations.model import (
    literal_rows,
)
from scopecat.compiler.relations.operators import (
    SCALAR_OPERATORS,
    ScalarOperator,
)
from scopecat.compiler.relations.point_domain import point_rows
from scopecat.compiler.relations.scalar_eval import eval_binary
from scopecat.compiler.relations.verification import RelationTypeBindings
from scopecat.compiler.semantic.model import (
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
)
from scopecat.compiler.semantic.operation_contract import (
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
from scopecat.compiler.semantic.verification import (
    verify_implementation_catalog,
    verify_semantic_graph,
)
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.program import CoreProgram
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import Float, Scalar, Table
from tests.testkit.authoring import load_config
from tests.testkit.local_materialization import materialize_local_execution
from tests.testkit.relation_plans import table_value_expr
from tests.testkit.typed_program import link_program

_FLOAT = Scalar(Float())


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


def test_contract_survives_every_local_compiler_boundary() -> None:
    graph, program = _compute_program("*")
    environment = validate_config_environment(load_config())

    linked = link_program(program, environment)
    bound = materialize_local_execution(linked)
    execution = bound

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
        call.semantic_operation_id: call.contract
        for call in bound.run_compute_operations
    } == {
        operation_id.qualified_name: contract
        for operation_id, contract in semantic_contracts.items()
    }
    compute_operations = execution.run_compute_operations
    assert {
        operation.semantic_operation_id: operation.contract
        for operation in compute_operations
    } == {
        operation_id.qualified_name: contract
        for operation_id, contract in semantic_contracts.items()
    }


def test_local_target_selection_reports_missing_implementation() -> None:
    _graph, program = _compute_program("+", include_scalar_implementation=False)
    environment = validate_config_environment(load_config())
    linked = link_program(program, environment)
    with pytest.raises(CheckFailed) as failure:
        materialize_local_execution(linked)

    assert {problem.code for problem in failure.value.problems} == {
        "semantic_operation_implementation_missing",
    }


def test_bound_compute_retains_semantic_contract() -> None:
    _add_graph, add_program = _compute_program("+")
    _multiply_graph, multiply_program = _compute_program("*")
    environment = validate_config_environment(load_config())

    add = materialize_local_execution(link_program(add_program, environment))
    multiply = materialize_local_execution(link_program(multiply_program, environment))

    add_call = add.run_compute_operations[-1]
    multiply_call = multiply.run_compute_operations[-1]
    assert add_call.semantic_operation_id == multiply_call.semantic_operation_id
    assert add_call.implementation_id == multiply_call.implementation_id
    assert add_call.inputs == multiply_call.inputs
    assert add_call.contract != multiply_call.contract


def _compute_program(
    operator: ScalarOperator,
    *,
    include_scalar_implementation: bool = True,
) -> tuple[SemanticGraphIR, CoreProgram]:
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
                source=OperationOutputSource(producer_id),
            ),
            ValueDef(
                id=literal_id,
                value_type=_FLOAT,
                source=LiteralValueSource(2.0),
            ),
            ValueDef(
                id=scalar_output_id,
                value_type=_FLOAT,
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
    program = CoreProgram(
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
