from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

import pytest
from hypothesis import given
from hypothesis import strategies as st

from scopecat.compiler.frontend.environment import validate_config_environment
from scopecat.compiler.linking.implementations import (
    select_local_implementations,
)
from scopecat.compiler.relations.point_domain import point_literal_rows
from scopecat.compiler.semantic.model import (
    ImplementationCatalog,
    ImplementationId,
    LocalPythonImplementation,
    OperationId,
    ValueId,
    operation_result_id,
)
from scopecat.compiler.semantic.operation_contract import (
    LOCAL_OPAQUE_OPERATION_CONTRACT,
    PlacementConstraint,
)
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.program import (
    CoreProgram,
    TypedComputeNode,
    TypedComputeOutput,
)
from scopecat.compiler.typed.verification import verify_core_program
from scopecat.execution.local.program import ComputeOperation
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import ProblemPhase
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import Float, Payload, Scalar, ValueType
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
) -> TypedComputeOutput:
    return TypedComputeOutput(
        id=value_id or operation_result_id(operation_id),
        value_type=value_type,
    )


def _program(
    *,
    catalog: ImplementationCatalog,
    output_type: ValueType = _FLOAT,
    output_id: ValueId | None = None,
    point_count: int = 1,
) -> CoreProgram:
    operation_id = _operation_id()
    return typed_program(
        id="implementation-sidecar",
        kind="compiler_test",
        point_domain=PointDomain(
            root=point_literal_rows(
                (),
                tuple(() for _index in range(point_count)),
            )
        ),
        compute_nodes=(
            TypedComputeNode(
                id=operation_id,
                contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
                result=_result(
                    operation_id,
                    output_type,
                    value_id=output_id,
                ),
            ),
        ),
        implementation_catalog=catalog,
    )


def _catalog(
    *implementations: tuple[str, OperationId, Callable[..., object]],
) -> ImplementationCatalog:
    return ImplementationCatalog(
        local_python=tuple(
            LocalPythonImplementation(
                id=ImplementationId(implementation_id),
                operation_id=operation_id,
                operation_contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
                kernel=kernel,
            )
            for implementation_id, operation_id, kernel in implementations
        )
    )


def test_linking_does_not_require_a_local_implementation() -> None:
    program = _program(catalog=ImplementationCatalog())
    environment = validate_config_environment(load_config())

    assert verify_core_program(program) is program
    linked = link_program(program, environment)
    with pytest.raises(CheckFailed) as failure:
        materialize_local_execution(linked)

    assert linked.program.compute_nodes[0].contract == program.compute_nodes[0].contract
    assert [problem.code for problem in failure.value.problems] == [
        "semantic_operation_implementation_missing"
    ]


def test_local_materialization_rejects_ambiguous_implementation() -> None:
    operation_id = _operation_id()
    program = _program(
        catalog=_catalog(
            ("python-v1", operation_id, lambda: 1.0),
            ("python-v2", operation_id, lambda: 2.0),
        )
    )

    environment = validate_config_environment(load_config())
    linked = link_program(program, environment)
    with pytest.raises(CheckFailed) as failure:
        materialize_local_execution(linked)

    assert [problem.code for problem in failure.value.problems] == [
        "semantic_operation_implementation_ambiguous"
    ]


@given(candidate_order=st.permutations(("python-v1", "python-v2")))
def test_ambiguous_selection_never_depends_on_catalog_order(
    candidate_order: list[str],
) -> None:
    operation_id = _operation_id()
    program = _program(
        catalog=_catalog(
            *(
                (implementation_id, operation_id, lambda: 1.0)
                for implementation_id in candidate_order
            )
        )
    )

    selected, problems = select_local_implementations(
        program.compute_nodes,
        program.implementation_catalog,
        phase=ProblemPhase.PLANNING,
    )

    assert selected is None
    assert [problem.code for problem in problems] == [
        "semantic_operation_implementation_ambiguous"
    ]


@pytest.mark.parametrize(
    "placement",
    (PlacementConstraint.HOST, PlacementConstraint.UNCONSTRAINED),
)
def test_local_selection_accepts_current_host_compatible_placements(
    placement: PlacementConstraint,
) -> None:
    operation_id = _operation_id()
    contract = replace(LOCAL_OPAQUE_OPERATION_CONTRACT, placement=placement)
    node = TypedComputeNode(
        id=operation_id,
        contract=contract,
        result=_result(operation_id),
    )
    catalog = ImplementationCatalog(
        local_python=(
            LocalPythonImplementation(
                id=ImplementationId("python-v1"),
                operation_id=operation_id,
                operation_contract=contract,
                kernel=lambda: 1.0,
            ),
        )
    )

    selected, problems = select_local_implementations(
        (node,),
        catalog,
        phase=ProblemPhase.PLANNING,
    )

    assert not problems
    assert selected is not None
    assert selected.entries[0].operation_contract == contract


@given(candidate_order=st.permutations(("first", "second")))
def test_selection_order_follows_typed_nodes_not_catalog(
    candidate_order: list[str],
) -> None:
    first_id = _operation_id("first")
    second_id = _operation_id("second")
    nodes = (
        TypedComputeNode(
            id=second_id,
            contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
            result=_result(second_id),
        ),
        TypedComputeNode(
            id=first_id,
            contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
            result=_result(first_id),
        ),
    )
    operation_ids = {"first": first_id, "second": second_id}
    catalog = _catalog(
        *(
            (
                f"python-{name}",
                operation_ids[name],
                lambda: 1.0,
            )
            for name in candidate_order
        )
    )

    selected, problems = select_local_implementations(
        nodes,
        catalog,
        phase=ProblemPhase.PLANNING,
    )

    assert not problems
    assert selected is not None
    assert [entry.operation_id for entry in selected.entries] == [
        second_id,
        first_id,
    ]


def test_incomplete_selection_never_returns_a_partial_artifact() -> None:
    first_id = _operation_id("first")
    second_id = _operation_id("second")
    nodes = tuple(
        TypedComputeNode(
            id=operation_id,
            contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
            result=_result(operation_id),
        )
        for operation_id in (first_id, second_id)
    )

    selected, problems = select_local_implementations(
        nodes,
        _catalog(("python-first", first_id, lambda: 1.0)),
        phase=ProblemPhase.PLANNING,
    )

    assert selected is None
    assert [problem.code for problem in problems] == [
        "semantic_operation_implementation_missing"
    ]


def test_binding_selects_stable_implementation_identity() -> None:
    operation_id = _operation_id()
    first = _program(
        catalog=_catalog(("python-v1", operation_id, lambda: 1.0)),
    )
    second = _program(
        catalog=_catalog(("python-v2", operation_id, lambda: 1.0)),
    )
    environment = validate_config_environment(load_config())

    first_plan = materialize_local_execution(link_program(first, environment))
    second_plan = materialize_local_execution(link_program(second, environment))

    first_call = first_plan.preamble_operations[0]
    second_call = second_plan.preamble_operations[0]
    assert first_call.semantic_operation_id == operation_id.qualified_name
    assert first_call.implementation_id == "python-v1"
    assert second_call.implementation_id == "python-v2"


def test_plan_pins_exact_callable_for_selected_implementation() -> None:
    operation_id = _operation_id()

    def first_kernel() -> float:
        return 1.0

    def second_kernel() -> float:
        return 2.0

    first_program = _program(
        catalog=_catalog(("python-v1", operation_id, first_kernel))
    )
    second_program = _program(
        catalog=_catalog(("python-v1", operation_id, second_kernel))
    )
    environment = validate_config_environment(load_config())
    plan = materialize_local_execution(link_program(first_program, environment))
    second_plan = materialize_local_execution(link_program(second_program, environment))

    assert plan.preamble_operations[0].kernel is first_kernel
    assert second_plan.preamble_operations[0].kernel is second_kernel


def test_dependency_free_compute_is_lowered_once_outside_point_effects() -> None:
    operation_id = _operation_id()
    program = _program(
        catalog=_catalog(("python-v1", operation_id, lambda: 1.0)),
        point_count=2,
    )
    materialized = materialize_local_execution(
        link_program(program, validate_config_environment(load_config())),
    )

    assert len(materialized.preamble_operations) == 1
    assert operations_of_type(materialized, ComputeOperation) == ()


def test_compute_result_identity_is_preserved_in_bound_calls() -> None:
    operation_id = _operation_id()
    catalog = _catalog(("python-v1", operation_id, lambda: 1.0))
    environment = validate_config_environment(load_config())
    first_output = ValueId(SymbolId(local_id="first-output"))
    second_output = ValueId(SymbolId(local_id="second-output"))

    first = materialize_local_execution(
        link_program(_program(catalog=catalog, output_id=first_output), environment)
    )
    second = materialize_local_execution(
        link_program(_program(catalog=catalog, output_id=second_output), environment)
    )

    first_call = first.preamble_operations[0]
    second_call = second.preamble_operations[0]
    assert first_call.result.id == first_output
    assert second_call.result.id == second_output


def test_compute_interface_accepts_payload_python_type() -> None:
    operation_id = _operation_id()
    program = _program(
        catalog=_catalog(("python-v1", operation_id, dict)),
        output_type=Scalar(Payload("program", python_type=dict)),
    )

    materialize_local_execution(
        link_program(program, validate_config_environment(load_config()))
    )
