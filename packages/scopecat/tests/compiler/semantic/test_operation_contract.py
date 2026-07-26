from __future__ import annotations

from functools import partial

from scopecat.compiler.frontend.assembly_lowering import lower_semantic_compute_graph
from scopecat.compiler.frontend.environment import build_config_environment
from scopecat.compiler.relations.operators import (
    ScalarOperator,
)
from scopecat.compiler.relations.point_domain import POINT_UNIT
from scopecat.compiler.relations.scalar_eval import eval_binary
from scopecat.compiler.relations.verification import RelationTypeBindings
from scopecat.compiler.semantic.model import (
    ImplementationId,
    LiteralValueSource,
    LocalPythonImplementation,
    OperationId,
    SemanticGraphIR,
    SemanticOperation,
    ValueDef,
    ValueId,
    ValueUse,
    operation_result_id,
)
from scopecat.compiler.semantic.operation_contract import (
    LOCAL_OPAQUE_OPERATION_CONTRACT,
    scalar_binary_operation_contract,
)
from scopecat.compiler.semantic.verification import verify_semantic_graph
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.program import CoreProgram
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import Float, Scalar
from tests.testkit.authoring import load_config
from tests.testkit.typed_program import link_program

_FLOAT = Scalar(Float())


def test_contract_survives_the_typed_compiler_boundary() -> None:
    graph, program = _compute_program("*")
    environment = build_config_environment(load_config())

    linked = link_program(program, environment)

    semantic_contracts = {
        operation.id: operation.contract for operation in graph.operations
    }
    assert {
        node.id: node.contract for node in program.compute_nodes
    } == semantic_contracts
    assert {
        node.id: node.contract for node in linked.program.compute_nodes
    } == semantic_contracts


def test_typed_compute_retains_distinct_semantic_contracts() -> None:
    _add_graph, add_program = _compute_program("+")
    _multiply_graph, multiply_program = _compute_program("*")

    add_node = add_program.compute_nodes[-1]
    multiply_node = multiply_program.compute_nodes[-1]
    assert add_node.id == multiply_node.id
    assert add_node.implementation == multiply_node.implementation
    assert add_node.contract != multiply_node.contract


def _compute_program(
    operator: ScalarOperator,
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
        result_id=producer_output_id,
        result_type=_FLOAT,
    )
    scalar = SemanticOperation(
        id=scalar_id,
        contract=scalar_binary_operation_contract(operator),
        inputs=(
            ("left", ValueUse(producer_output_id)),
            ("right", ValueUse(literal_id)),
        ),
        result_id=scalar_output_id,
        result_type=_FLOAT,
    )
    graph = SemanticGraphIR(
        value_defs=(
            ValueDef(
                id=literal_id,
                value_type=_FLOAT,
                source=LiteralValueSource(2.0),
            ),
        ),
        operations=(scalar, producer),
    )
    verified = verify_semantic_graph(graph)
    implementations = {
        producer_id: LocalPythonImplementation(
            ImplementationId("python.produce.v1"),
            lambda: 3.0,
        ),
        scalar_id: LocalPythonImplementation(
            ImplementationId("python.combine.v1"),
            partial(eval_binary, operator),
        ),
    }
    nodes = lower_semantic_compute_graph(
        verified,
        implementations,
        {},
        type_bindings=RelationTypeBindings(),
    )
    program = CoreProgram(
        id="operation-contract-program",
        kind="compiler_test",
        point_domain=_point_domain(),
        compute_nodes=nodes,
    )
    return verified.graph, program


def _point_domain() -> PointDomain:
    return PointDomain(root=POINT_UNIT)
