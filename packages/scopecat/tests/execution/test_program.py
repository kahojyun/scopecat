from __future__ import annotations

from dataclasses import replace

from scopecat.compiler.linking.bound import (
    BoundCollect,
    BoundComputeCall,
    BoundComputeOutput,
    BoundComputeResult,
    BoundPlan,
    BoundPoint,
    BoundResourceState,
    BoundStateField,
    CollectionRequest,
)
from scopecat.compiler.linking.implementations import select_local_implementations
from scopecat.compiler.linking.product_realizations import (
    select_local_product_realizations,
)
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
    operation_result_id,
)
from scopecat.compiler.semantic.operation_contract import (
    LOCAL_OPAQUE_OPERATION_CONTRACT,
)
from scopecat.compiler.typed.point_domain import LogicalPointId, PointDomainId
from scopecat.compiler.typed.products import ProductDef
from scopecat.compiler.typed.program import (
    ComputeEdge,
    TypedComputeNode,
    TypedComputeOutput,
)
from scopecat.execution.local.lowering import build_execution_program
from scopecat.execution.local.program import (
    ApplyStateStage,
    CollectionResultBinding,
    CollectOperation,
    CollectStage,
    ComputeStage,
    ExecutionProgram,
    OutputInput,
    PointProgram,
    ResourceClaim,
)
from scopecat.kernel.problems import ProblemPhase
from scopecat.kernel.product_identity import product_id, product_use
from scopecat.kernel.resource_identity import PhysicalResourceId
from scopecat.kernel.state import StateValue
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import Float, Scalar
from scopecat.planning.routing import RoutingView
from scopecat.records.config import RoutingResource
from scopecat.sdk.instruments.contracts import CollectCommand, CollectProductRequest
from tests.testkit.typed_program import instrument_product_producer


def test_execution_program_has_explicit_ordered_effect_stages() -> None:
    producer_id = OperationId(SymbolId(local_id="produce"))
    consumer_id = OperationId(SymbolId(local_id="consume"))
    producer_result_id = operation_result_id(producer_id)
    consumer_result_id = operation_result_id(consumer_id)
    availability = ValueAvailability(ValueStage.EXECUTE, ValueRate.POINT)

    def produce() -> float:
        return 1.0

    def consume(*, value: float) -> float:
        return value + 1.0

    catalog = ImplementationCatalog(
        local_python=(
            LocalPythonImplementation(
                id=ImplementationId("python.produce.v1"),
                operation_id=producer_id,
                operation_contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
                kernel=produce,
            ),
            LocalPythonImplementation(
                id=ImplementationId("python.consume.v1"),
                operation_id=consumer_id,
                operation_contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
                kernel=consume,
            ),
        )
    )
    local_implementations, problems = select_local_implementations(
        (
            TypedComputeNode(
                id=producer_id,
                contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
                result=TypedComputeOutput(
                    id=producer_result_id,
                    value_type=Scalar(Float()),
                    availability=availability,
                ),
            ),
            TypedComputeNode(
                id=consumer_id,
                contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
                inputs={
                    "value": ComputeEdge(
                        value_id=producer_result_id,
                        expected_type=Scalar(Float()),
                    )
                },
                result=TypedComputeOutput(
                    id=consumer_result_id,
                    value_type=Scalar(Float()),
                    availability=availability,
                ),
            ),
        ),
        catalog,
        phase=ProblemPhase.PLANNING,
    )
    assert not problems
    assert local_implementations is not None
    source_a_product = ProductDef(
        id=product_id("source-a-signal"),
        unit="ratio",
        dtype="float64",
    )
    source_b_product = replace(
        source_a_product,
        id=product_id("source-b-signal"),
    )
    source_a_producer = instrument_product_producer(
        source_a_product,
        physical_resource_id="source-a",
        capability="scalar_signal",
        provider_key="signal",
    )
    source_b_producer = instrument_product_producer(
        source_b_product,
        physical_resource_id="source-b",
        capability="scalar_signal",
        provider_key="signal",
    )
    source_a_signal = product_use(source_a_product.id)
    source_b_signal = product_use(source_b_product.id)
    point = BoundPoint(
        point_index=0,
        logical_id=LogicalPointId(PointDomainId("test-program", "root"), 0),
        row={},
        coordinates={},
        compute=(
            BoundComputeCall(
                operation_id=producer_id,
                implementation=local_implementations.selected_for(producer_id),
                contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
                inputs={},
                result=BoundComputeResult(
                    id=producer_result_id,
                    value_type=Scalar(Float()),
                ),
                cache_key="producer-key",
            ),
            BoundComputeCall(
                operation_id=consumer_id,
                implementation=local_implementations.selected_for(consumer_id),
                contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
                inputs={"value": BoundComputeOutput(producer_result_id)},
                result=BoundComputeResult(
                    id=consumer_result_id,
                    value_type=Scalar(Float()),
                ),
                cache_key="consumer-key",
            ),
        ),
        routes=(),
        desired_state=(
            _gain_state("source-a", 1.0),
            _gain_state("source-b", 2.0),
        ),
        collect=(
            BoundCollect(
                resource_id=PhysicalResourceId("source-a"),
                requests=(
                    CollectionRequest(
                        product_use_id=source_a_signal.id,
                        product_id=source_a_product.id,
                        provider_key="signal",
                        capability="scalar_signal",
                        unit="ratio",
                        dtype="float64",
                    ),
                ),
            ),
            BoundCollect(
                resource_id=PhysicalResourceId("source-b"),
                requests=(
                    CollectionRequest(
                        product_use_id=source_b_signal.id,
                        product_id=source_b_product.id,
                        provider_key="signal",
                        capability="scalar_signal",
                        unit="ratio",
                        dtype="float64",
                    ),
                ),
            ),
        ),
    )
    plan = BoundPlan(
        experiment_id="explicit-stages",
        points=(point,),
        product_uses=(source_a_signal, source_b_signal),
        local_product_realizations=select_local_product_realizations(
            (source_a_product, source_b_product),
            (source_a_producer, source_b_producer),
            (source_a_signal, source_b_signal),
            routing=RoutingView(
                resources=(
                    RoutingResource(
                        id="source-a",
                        capabilities=["scalar_signal"],
                    ),
                    RoutingResource(
                        id="source-b",
                        capabilities=["scalar_signal"],
                    ),
                )
            ),
        )[0],
    )

    program = build_execution_program(
        plan,
        instrument_order=("source-b", "source-c", "source-a"),
    )

    compute, state, collect = program.points[0].stages
    assert isinstance(compute, ComputeStage)
    assert isinstance(state, ApplyStateStage)
    assert isinstance(collect, CollectStage)
    assert [operation.semantic_operation_id for operation in compute.operations] == [
        "produce",
        "consume",
    ]
    assert [operation.implementation_id for operation in compute.operations] == [
        "python.produce.v1",
        "python.consume.v1",
    ]
    assert compute.operations[1].inputs["value"] == OutputInput(producer_result_id)
    assert compute.operations[0].result.id == producer_result_id
    assert compute.operations[1].result.id == consumer_result_id
    assert [operation.instrument_id for operation in state.operations] == [
        "source-b",
        "source-a",
    ]
    assert [operation.instrument_id for operation in collect.operations] == [
        "source-b",
        "source-a",
    ]
    assert program.collection_product_use_ids == (
        source_a_signal.id,
        source_b_signal.id,
    )
    assert all(
        operation.command.operation_id == operation.operation_id
        for operation in collect.operations
    )
    assert program.resource_order == ("source-b", "source-a")
    assert [claim.id for claim in program.resource_claims] == [
        "source-b",
        "source-a",
    ]


def test_collection_inventory_is_a_subset_of_complete_logical_uses() -> None:
    program = _source_and_derived_execution_program()
    source_use, derived_use = program.product_uses

    assert program.collection_product_use_ids == (source_use.id,)
    assert derived_use.id not in program.collection_product_use_ids


def test_zero_point_execution_retains_nonempty_collection_inventory() -> None:
    source_use = product_use(product_id("source"))

    program = ExecutionProgram(
        experiment_id="zero-point-collection-contract",
        points=(),
        product_uses=(source_use,),
        collection_product_use_ids=(source_use.id,),
        resource_order=(),
        resource_claims=(),
    )

    assert program.collection_product_use_ids == (source_use.id,)


def _source_and_derived_execution_program() -> ExecutionProgram:
    source_use = product_use(product_id("source"))
    derived_use = product_use(product_id("derived"))
    operation_id = "point-0.collect.source-0"
    collect = CollectOperation(
        operation_id=operation_id,
        instrument_id="source-0",
        command=CollectCommand(
            operation_id=operation_id,
            instrument_id="source-0",
            point_index=0,
            point_count=1,
            requests=[CollectProductRequest(id="source")],
        ),
        result_bindings=(
            CollectionResultBinding(
                provider_key="source",
                product_use_id=source_use.id,
                product_id=source_use.product_id,
            ),
        ),
    )
    return ExecutionProgram(
        experiment_id="source-and-derived",
        points=(
            PointProgram(
                point_index=0,
                point_uid="point-0",
                coordinates={},
                stages=(CollectStage(operations=(collect,)),),
            ),
        ),
        product_uses=(source_use, derived_use),
        collection_product_use_ids=(source_use.id,),
        resource_order=("source-0",),
        resource_claims=(ResourceClaim(id="source-0"),),
    )


def _gain_state(instrument_id: str, value: float) -> BoundResourceState:
    return BoundResourceState(
        resource_id=PhysicalResourceId(instrument_id),
        capability_id="set_gain",
        fields=(BoundStateField(field_path="gain", value=StateValue(value)),),
    )
