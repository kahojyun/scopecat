from __future__ import annotations

from collections.abc import Callable

from scopecat.compiler.semantic.model import (
    ImplementationId,
    LocalPythonImplementation,
)
from scopecat.compiler.semantic.operation_contract import (
    LOCAL_OPAQUE_OPERATION_CONTRACT,
)
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.program import (
    CoreProgram,
    TypedComputeNode,
)
from scopecat.config.environment import build_config_environment
from scopecat.execution.local.program import ComputeOperation
from scopecat.graph.relations.point_domain import point_axis_values
from scopecat.graph.values import (
    ComputeOutput,
    OperationId,
    ValueId,
    operation_result_id,
)
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import Float, Int, Payload, Scalar, ValueType
from tests.testkit.authoring import load_config
from tests.testkit.local_materialization import (
    materialize_local_execution,
    operations_of_type,
)
from tests.testkit.typed_program import link_program, typed_program

_FLOAT = Scalar(Float())


def _operation_id(local_id: str = "compute") -> OperationId:
    return OperationId(SymbolId(local_id=local_id))


def _result(
    operation_id: OperationId,
    value_type: ValueType = _FLOAT,
    *,
    value_id: ValueId | None = None,
) -> ComputeOutput:
    return ComputeOutput(
        id=value_id or operation_result_id(operation_id),
        value_type=value_type,
    )


def _program(
    *,
    implementation_id: str = "python-v1",
    kernel: Callable[..., object] = lambda: 1.0,
    output_type: ValueType = _FLOAT,
    output_id: ValueId | None = None,
    point_count: int = 1,
) -> CoreProgram:
    operation_id = _operation_id()
    return typed_program(
        id="implementation-sidecar",
        kind="compiler_test",
        point_domain=PointDomain(
            root=point_axis_values(
                "point_index",
                Scalar(Int()),
                tuple(range(point_count)),
            )
        ),
        compute_nodes=(
            TypedComputeNode(
                id=operation_id,
                contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
                implementation=LocalPythonImplementation(
                    id=ImplementationId(implementation_id),
                    kernel=kernel,
                ),
                result=_result(
                    operation_id,
                    output_type,
                    value_id=output_id,
                ),
            ),
        ),
    )


def test_binding_preserves_stable_implementation_identity() -> None:
    operation_id = _operation_id()
    first = _program(
        implementation_id="python-v1",
    )
    second = _program(
        implementation_id="python-v2",
    )
    environment = build_config_environment(load_config())

    first_plan = materialize_local_execution(link_program(first, environment))
    second_plan = materialize_local_execution(link_program(second, environment))

    first_call = first_plan.preamble_operations[0]
    second_call = second_plan.preamble_operations[0]
    assert first_call.semantic_operation_id == operation_id.qualified_name
    assert first_call.implementation_id == "python-v1"
    assert second_call.implementation_id == "python-v2"


def test_plan_pins_exact_implementation_callable() -> None:
    def first_kernel() -> float:
        return 1.0

    def second_kernel() -> float:
        return 2.0

    first_program = _program(
        implementation_id="python-v1",
        kernel=first_kernel,
    )
    second_program = _program(
        implementation_id="python-v1",
        kernel=second_kernel,
    )
    environment = build_config_environment(load_config())
    plan = materialize_local_execution(link_program(first_program, environment))
    second_plan = materialize_local_execution(link_program(second_program, environment))

    assert plan.preamble_operations[0].kernel is first_kernel
    assert second_plan.preamble_operations[0].kernel is second_kernel


def test_dependency_free_compute_is_lowered_once_outside_point_effects() -> None:
    program = _program(
        point_count=2,
    )
    materialized = materialize_local_execution(
        link_program(program, build_config_environment(load_config())),
    )

    assert len(materialized.preamble_operations) == 1
    assert operations_of_type(materialized, ComputeOperation) == ()


def test_compute_result_identity_is_preserved_in_bound_calls() -> None:
    environment = build_config_environment(load_config())
    first_output = ValueId(SymbolId(local_id="first-output"))
    second_output = ValueId(SymbolId(local_id="second-output"))

    first = materialize_local_execution(
        link_program(_program(output_id=first_output), environment)
    )
    second = materialize_local_execution(
        link_program(_program(output_id=second_output), environment)
    )

    first_call = first.preamble_operations[0]
    second_call = second.preamble_operations[0]
    assert first_call.result.id == first_output
    assert second_call.result.id == second_output


def test_compute_interface_accepts_payload_python_type() -> None:
    program = _program(
        kernel=dict,
        output_type=Scalar(Payload("program", python_type=dict)),
    )

    materialize_local_execution(
        link_program(program, build_config_environment(load_config()))
    )
