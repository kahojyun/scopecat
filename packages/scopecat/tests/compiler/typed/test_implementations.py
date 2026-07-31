from __future__ import annotations

from collections.abc import Callable

from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.program import (
    BoundProgramFacts,
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
from scopecat.kernel.value_types import Float, Int, Payload, Scalar
from scopecat.program.logical import (
    ImplementationId,
    LocalPythonImplementation,
)
from tests.testkit.authoring import load_config
from tests.testkit.local_materialization import (
    materialize_local_execution,
    operations_of_type,
)
from tests.testkit.typed_program import bind_program_facts, typed_program

_FLOAT = Scalar(Float())


def _operation_id(local_id: str = "compute") -> OperationId:
    return OperationId(SymbolId(local_id=local_id))


def _result(
    operation_id: OperationId,
    value_type: Scalar = _FLOAT,
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
    output_type: Scalar = _FLOAT,
    output_id: ValueId | None = None,
    point_count: int = 1,
) -> BoundProgramFacts:
    operation_id = _operation_id()
    return typed_program(
        id="implementation-sidecar",
        kind="compiler_test",
        point_domain=PointDomain(
            axes=(
                point_axis_values(
                    "point_index",
                    Scalar(Int()),
                    tuple(range(point_count)),
                ),
            )
        ),
        compute_nodes=(
            TypedComputeNode(
                id=operation_id,
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

    first_plan = materialize_local_execution(bind_program_facts(first, environment))
    second_plan = materialize_local_execution(bind_program_facts(second, environment))

    first_call = operations_of_type(first_plan, ComputeOperation, point_index=0)[0]
    second_call = operations_of_type(second_plan, ComputeOperation, point_index=0)[0]
    assert first_call.logical_compute_node_id == operation_id.qualified_name
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
    plan = materialize_local_execution(bind_program_facts(first_program, environment))
    second_plan = materialize_local_execution(
        bind_program_facts(second_program, environment)
    )

    assert operations_of_type(plan, ComputeOperation, point_index=0)[0].kernel is (
        first_kernel
    )
    assert (
        operations_of_type(
            second_plan,
            ComputeOperation,
            point_index=0,
        )[0].kernel
        is second_kernel
    )


def test_dependency_free_compute_is_lowered_for_each_point() -> None:
    program = _program(
        point_count=2,
    )
    materialized = materialize_local_execution(
        bind_program_facts(program, build_config_environment(load_config())),
    )

    calls = operations_of_type(materialized, ComputeOperation)
    assert len(calls) == 2
    assert len({call.operation_id for call in calls}) == 2


def test_compute_result_identity_is_preserved_in_bound_calls() -> None:
    environment = build_config_environment(load_config())
    first_output = ValueId(SymbolId(local_id="first-output"))
    second_output = ValueId(SymbolId(local_id="second-output"))

    first = materialize_local_execution(
        bind_program_facts(_program(output_id=first_output), environment)
    )
    second = materialize_local_execution(
        bind_program_facts(_program(output_id=second_output), environment)
    )

    first_call = operations_of_type(first, ComputeOperation, point_index=0)[0]
    second_call = operations_of_type(second, ComputeOperation, point_index=0)[0]
    assert first_call.result.id == first_output
    assert second_call.result.id == second_output


def test_compute_interface_accepts_payload_schema() -> None:
    program = _program(
        kernel=dict,
        output_type=Scalar(Payload("program")),
    )

    materialize_local_execution(
        bind_program_facts(program, build_config_environment(load_config()))
    )
