from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import replace

import pytest
from hypothesis import given
from hypothesis import strategies as st

from scopecat.compiler.frontend.environment import validate_config_environment
from scopecat.compiler.linking.bound import BoundValue
from scopecat.compiler.linking.implementations import (
    select_local_implementations,
)
from scopecat.compiler.linking.linked import link_program
from scopecat.compiler.linking.materialization import materialize_local_plan
from scopecat.compiler.relations.backend import PreparedRelationEvaluation
from scopecat.compiler.relations.model import (
    RelationExpr,
    Row,
    literal_rows,
)
from scopecat.compiler.relations.reference_backend import ReferenceRelationBackend
from scopecat.compiler.semantic.availability import (
    ValueAvailability,
    ValueRate,
    ValueStage,
)
from scopecat.compiler.semantic.model import (
    ImplementationCatalog,
    ImplementationId,
    LocalPythonImplementation,
    OperationId,
    SourceAnchor,
    SourceMap,
    ValueId,
    operation_result_id,
)
from scopecat.compiler.semantic.operation_contract import (
    LOCAL_OPAQUE_OPERATION_CONTRACT,
    PlacementConstraint,
    Portability,
    scalar_binary_operation_contract,
)
from scopecat.compiler.typed.program import (
    TypedComputeNode,
    TypedComputeOutput,
    TypedProgram,
    typed_program,
)
from scopecat.compiler.typed.verification import verify_typed_program
from scopecat.execution.local.lowering import build_execution_program
from scopecat.execution.local.program import ComputeStage
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import ProblemPhase
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import Float, Payload, Scalar, String, Table, ValueType
from tests.testkit.authoring import load_config
from tests.testkit.relation_plans import point_domain

_FLOAT = Scalar(Float())
_EXECUTE_POINT = ValueAvailability(ValueStage.EXECUTE, ValueRate.POINT)


class _TrackingBackend(ReferenceRelationBackend):
    materialization_count: int

    def __init__(self) -> None:
        super().__init__(backend_id="tests.compute-availability")
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


def _operation_id(local_id: str = "compute") -> OperationId:
    return OperationId(SymbolId(local_id=local_id))


def _result(
    operation_id: OperationId,
    value_type: ValueType = _FLOAT,
    *,
    value_id: ValueId | None = None,
    availability: ValueAvailability = _EXECUTE_POINT,
) -> TypedComputeOutput:
    return TypedComputeOutput(
        id=value_id or operation_result_id(operation_id),
        value_type=value_type,
        availability=availability,
    )


def _program(
    *,
    catalog: ImplementationCatalog,
    source_map: SourceMap | None = None,
    output_type: ValueType = _FLOAT,
    output_id: ValueId | None = None,
    output_availability: ValueAvailability = _EXECUTE_POINT,
    point_count: int = 1,
) -> TypedProgram:
    operation_id = _operation_id()
    return typed_program(
        id="implementation-sidecar",
        kind="compiler_test",
        point_domain=point_domain(
            literal_rows([{} for _index in range(point_count)]),
            expected_type=Table(
                columns=(),
                min_rows=point_count,
                max_rows=point_count,
            ),
        ),
        compute_nodes=(
            TypedComputeNode(
                id=operation_id,
                contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
                result=_result(
                    operation_id,
                    output_type,
                    value_id=output_id,
                    availability=output_availability,
                ),
            ),
        ),
        implementation_catalog=catalog,
        source_map=source_map,
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


def test_typed_program_keeps_implementation_and_source_as_sidecars() -> None:
    operation_id = _operation_id()
    catalog = _catalog(("python-v1", operation_id, lambda: 1.0))
    source_map = SourceMap(
        operation_sources=(
            (
                operation_id,
                SourceAnchor(kind="compute", declaration_id="declaration"),
            ),
        )
    )

    program = _program(catalog=catalog, source_map=source_map)

    assert program.implementation_catalog is catalog
    assert program.source_map is source_map


def test_declared_implementation_contract_must_match_typed_operation() -> None:
    operation_id = _operation_id()
    program = _program(
        catalog=ImplementationCatalog(
            local_python=(
                LocalPythonImplementation(
                    id=ImplementationId("python-v1"),
                    operation_id=operation_id,
                    operation_contract=scalar_binary_operation_contract("+"),
                    kernel=lambda: 1.0,
                ),
            )
        )
    )

    with pytest.raises(CheckFailed) as caught:
        verify_typed_program(program)

    assert [problem.code for problem in caught.value.problems] == [
        "semantic_implementation_contract_mismatch"
    ]


def test_linking_does_not_require_a_local_implementation() -> None:
    program = _program(catalog=ImplementationCatalog())
    environment = validate_config_environment(load_config())

    assert verify_typed_program(program) is program
    linked = link_program(program, environment)
    plan = materialize_local_plan(linked)

    assert linked.program.compute_nodes[0].contract == program.compute_nodes[0].contract
    assert not plan.valid
    assert plan.points == ()
    assert plan.local_implementations is None
    assert [problem.code for problem in plan.problems] == [
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
    plan = materialize_local_plan(linked)

    assert not plan.valid
    assert plan.points == ()
    assert plan.local_implementations is None
    assert [problem.code for problem in plan.problems] == [
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


def test_malformed_candidate_does_not_create_a_false_ambiguity() -> None:
    operation_id = _operation_id()
    node = TypedComputeNode(
        id=operation_id,
        contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
        result=_result(operation_id),
    )
    catalog = ImplementationCatalog(
        local_python=(
            LocalPythonImplementation(
                id=ImplementationId("exact"),
                operation_id=operation_id,
                operation_contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
                kernel=lambda: 1.0,
            ),
            LocalPythonImplementation(
                id=ImplementationId("mismatch"),
                operation_id=operation_id,
                operation_contract=scalar_binary_operation_contract("+"),
                kernel=lambda: 2.0,
            ),
        )
    )

    selected, problems = select_local_implementations(
        (node,),
        catalog,
        phase=ProblemPhase.PLANNING,
    )

    assert selected is None
    assert [problem.code for problem in problems] == [
        "semantic_implementation_contract_mismatch"
    ]


@given(candidate_order=st.permutations(("exact", "mismatch")))
def test_duplicate_diagnostics_ignore_catalog_tie_order(
    candidate_order: list[str],
) -> None:
    operation_id = _operation_id()
    contracts = {
        "exact": LOCAL_OPAQUE_OPERATION_CONTRACT,
        "mismatch": scalar_binary_operation_contract("+"),
    }
    node = TypedComputeNode(
        id=operation_id,
        contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
        result=_result(operation_id),
    )
    catalog = ImplementationCatalog(
        local_python=tuple(
            LocalPythonImplementation(
                id=ImplementationId("shared"),
                operation_id=operation_id,
                operation_contract=contracts[kind],
                kernel=lambda: 1.0,
            )
            for kind in candidate_order
        )
    )

    selected, problems = select_local_implementations(
        (node,),
        catalog,
        phase=ProblemPhase.PLANNING,
    )

    assert selected is None
    assert [problem.code for problem in problems] == [
        "semantic_implementation_duplicate",
        "semantic_implementation_contract_mismatch",
    ]


def test_local_selection_rejects_intrinsically_invalid_contract() -> None:
    operation_id = _operation_id()
    invalid_contract = replace(
        LOCAL_OPAQUE_OPERATION_CONTRACT,
        portability=Portability.PORTABLE,
    )
    node = TypedComputeNode(
        id=operation_id,
        contract=invalid_contract,
        result=_result(operation_id),
    )
    catalog = ImplementationCatalog(
        local_python=(
            LocalPythonImplementation(
                id=ImplementationId("invalid"),
                operation_id=operation_id,
                operation_contract=invalid_contract,
                kernel=lambda: 1.0,
            ),
        )
    )

    selected, problems = select_local_implementations(
        (node,),
        catalog,
        phase=ProblemPhase.PLANNING,
    )

    assert selected is None
    assert [problem.code for problem in problems] == [
        "semantic_operation_local_target_unsupported"
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


def test_binding_selects_stable_implementation_and_hashes_its_identity() -> None:
    operation_id = _operation_id()
    first = _program(
        catalog=_catalog(("python-v1", operation_id, lambda: 1.0)),
    )
    second = _program(
        catalog=_catalog(("python-v2", operation_id, lambda: 1.0)),
    )
    environment = validate_config_environment(load_config())

    first_plan = materialize_local_plan(link_program(first, environment))
    second_plan = materialize_local_plan(link_program(second, environment))

    first_call = first_plan.points[0].compute[0]
    second_call = second_plan.points[0].compute[0]
    assert first_call.operation_id == operation_id
    assert first_call.implementation_id == ImplementationId("python-v1")
    assert first_call.cache_key != second_call.cache_key


def test_bound_plan_pins_selection_and_execution_only_projects_it() -> None:
    operation_id = _operation_id()

    def kernel() -> float:
        return 1.0

    program = _program(
        catalog=_catalog(("python-v1", operation_id, kernel)),
    )
    plan = materialize_local_plan(
        link_program(program, validate_config_environment(load_config()))
    )

    execution = build_execution_program(plan)

    call = plan.points[0].compute[0]
    assert not hasattr(plan, "implementation_catalog")
    assert plan.local_implementations is not None
    assert plan.local_implementations.selected_for(operation_id) is call.implementation
    assert call.implementation.kernel is kernel
    stage = execution.points[0].stages[0]
    assert isinstance(stage, ComputeStage)
    assert stage.operations[0].semantic_operation_id == "compute"
    assert stage.operations[0].implementation_id == "python-v1"
    assert stage.operations[0].kernel is kernel


def test_sealed_selection_is_shared_safely_across_defensive_copies() -> None:
    operation_id = _operation_id()
    plan = materialize_local_plan(
        link_program(
            _program(
                catalog=_catalog(("python-v1", operation_id, lambda: 1.0)),
            ),
            validate_config_environment(load_config()),
        )
    )

    copied = deepcopy(plan)

    assert copied.local_implementations is plan.local_implementations
    assert (
        copied.points[0].compute[0].implementation
        is plan.points[0].compute[0].implementation
    )


def test_implementation_id_versions_cache_while_plan_pins_exact_callable() -> None:
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
    plan = materialize_local_plan(link_program(first_program, environment))
    second_plan = materialize_local_plan(link_program(second_program, environment))

    assert (
        plan.points[0].compute[0].cache_key
        == second_plan.points[0].compute[0].cache_key
    )
    assert plan.points[0].compute[0].implementation.kernel is first_kernel
    assert second_plan.points[0].compute[0].implementation.kernel is second_kernel
    assert second_plan.local_implementations is not None

    with pytest.raises(ValueError, match="exact selected implementation"):
        replace(
            plan,
            local_implementations=second_plan.local_implementations,
        )
    with pytest.raises(ValueError, match="compute definition inventory"):
        replace(
            plan,
            points=(replace(plan.points[0], compute=()),),
        )
    drifted_call = replace(
        plan.points[0].compute[0],
        result=replace(
            plan.points[0].compute[0].result,
            id=ValueId(SymbolId(local_id="drifted-result")),
        ),
    )
    with pytest.raises(ValueError, match="exact declared result facts"):
        replace(
            plan,
            points=(replace(plan.points[0], compute=(drifted_call,)),),
        )
    with pytest.raises(ValueError, match="cover the compute inventory"):
        replace(plan, compute_definitions=())
    with pytest.raises(ValueError, match="valid bound plans require"):
        replace(plan, local_implementations=None)


def test_zero_point_plan_retains_complete_local_selection() -> None:
    operation_id = _operation_id()
    program = _program(
        catalog=_catalog(("python-v1", operation_id, lambda: 1.0)),
        point_count=0,
    )

    plan = materialize_local_plan(
        link_program(program, validate_config_environment(load_config()))
    )

    assert plan.valid
    assert plan.points == ()
    assert plan.local_implementations is not None
    assert [entry.operation_id for entry in plan.local_implementations.entries] == [
        operation_id
    ]
    assert len(plan.compute_definitions) == 1
    definition = plan.compute_definitions[0]
    assert definition.operation_id == operation_id
    assert definition.result.id == program.compute_nodes[0].result.id
    assert definition.result.value_type == program.compute_nodes[0].result.value_type
    assert (
        definition.result.availability == program.compute_nodes[0].result.availability
    )


def test_unsupported_local_result_availability_fails_before_point_evaluation() -> None:
    operation_id = _operation_id()
    availability = ValueAvailability(ValueStage.EXECUTE, ValueRate.RUN)
    program = _program(
        catalog=_catalog(("python-v1", operation_id, lambda: 1.0)),
        output_availability=availability,
    )
    backend = _TrackingBackend()

    plan = materialize_local_plan(
        link_program(program, validate_config_environment(load_config())),
        relation_backend=backend,
    )

    assert not plan.valid
    assert plan.points == ()
    assert plan.local_implementations is None
    assert plan.compute_definitions[0].result.availability == availability
    assert [problem.code for problem in plan.problems] == [
        "semantic_operation_local_output_availability_unsupported"
    ]
    assert backend.materialization_count == 0


def test_compute_result_identity_does_not_change_value_cache_semantics() -> None:
    operation_id = _operation_id()
    catalog = _catalog(("python-v1", operation_id, lambda: 1.0))
    environment = validate_config_environment(load_config())
    first_output = ValueId(SymbolId(local_id="first-output"))
    second_output = ValueId(SymbolId(local_id="second-output"))

    first = materialize_local_plan(
        link_program(_program(catalog=catalog, output_id=first_output), environment)
    )
    second = materialize_local_plan(
        link_program(_program(catalog=catalog, output_id=second_output), environment)
    )

    first_call = first.points[0].compute[0]
    second_call = second.points[0].compute[0]
    assert first_call.result.id == first_output
    assert second_call.result.id == second_output
    assert first_call.cache_key == second_call.cache_key


def test_compute_cache_identity_includes_selected_typed_interface() -> None:
    operation_id = _operation_id()
    catalog = _catalog(("python-v1", operation_id, lambda: 1.0))
    environment = validate_config_environment(load_config())

    float_plan = materialize_local_plan(
        link_program(_program(catalog=catalog), environment)
    )
    string_plan = materialize_local_plan(
        link_program(
            _program(catalog=catalog, output_type=Scalar(String())), environment
        )
    )

    assert (
        float_plan.points[0].compute[0].cache_key
        != string_plan.points[0].compute[0].cache_key
    )


def test_compute_interface_cache_accepts_payload_python_type() -> None:
    operation_id = _operation_id()
    program = _program(
        catalog=_catalog(("python-v1", operation_id, dict)),
        output_type=Scalar(Payload("program", python_type=dict)),
    )

    plan = materialize_local_plan(
        link_program(program, validate_config_environment(load_config()))
    )

    assert plan.valid
    assert plan.points[0].compute[0].cache_key


def test_bound_call_rejects_selection_and_interface_drift_at_construction() -> None:
    operation_id = _operation_id()
    plan = materialize_local_plan(
        link_program(
            _program(
                catalog=_catalog(("python-v1", operation_id, lambda: 1.0)),
            ),
            validate_config_environment(load_config()),
        )
    )

    with pytest.raises(ValueError, match="output type"):
        replace(
            plan.points[0].compute[0],
            result=replace(
                plan.points[0].compute[0].result,
                value_type=Scalar(String()),
            ),
        )
    with pytest.raises(ValueError, match="own the invoked operation"):
        replace(
            plan.points[0].compute[0],
            operation_id=_operation_id("other"),
        )
    with pytest.raises(ValueError, match="contract does not match"):
        replace(
            plan.points[0].compute[0],
            contract=scalar_binary_operation_contract("+"),
        )
    with pytest.raises(ValueError, match="inputs do not match"):
        replace(
            plan.points[0].compute[0],
            inputs={"extra": BoundValue(1.0)},
        )


def test_valid_bound_plan_rejects_nonlocal_compute_result_availability() -> None:
    operation_id = _operation_id()
    plan = materialize_local_plan(
        link_program(
            _program(
                catalog=_catalog(("python-v1", operation_id, lambda: 1.0)),
            ),
            validate_config_environment(load_config()),
        )
    )
    definition = plan.compute_definitions[0]
    unsupported = replace(
        definition,
        result=replace(
            definition.result,
            availability=ValueAvailability(ValueStage.RESULT, ValueRate.ROW),
        ),
    )

    with pytest.raises(ValueError, match="execute/point compute results"):
        replace(plan, compute_definitions=(unsupported,))
