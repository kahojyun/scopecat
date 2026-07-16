from __future__ import annotations

from dataclasses import replace
from typing import cast

import pytest

from scopecat.compiler.linking.bound import (
    BoundCollect,
    BoundComputeCall,
    BoundComputeDefinition,
    BoundComputeOutput,
    BoundComputeResult,
    BoundPlan,
    BoundPoint,
    BoundRecord,
    BoundResourceState,
    BoundStateField,
    CollectionRequest,
)
from scopecat.compiler.linking.implementations import select_local_implementations
from scopecat.compiler.linking.product_realizations import (
    select_local_product_realizations,
)
from scopecat.compiler.relations.evaluation import ParameterRelationData
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
    ValueId,
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
    instrument_product_producer,
)
from scopecat.compiler.typed.records import RecordUse
from scopecat.execution.local.lowering import build_execution_program
from scopecat.execution.local.program import (
    ApplyStateStage,
    CollectionResultBinding,
    CollectOperation,
    CollectStage,
    ComputeOperation,
    ComputeResultSlot,
    ComputeStage,
    ExecutionProgram,
    OutputInput,
    PointProgram,
    RecordProjection,
    ResourceClaim,
)
from scopecat.kernel.problems import ProblemPhase
from scopecat.kernel.product_identity import ProductUseId, product_id, product_use
from scopecat.kernel.resource_identity import physical_resource_id
from scopecat.kernel.state import StateValue
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import Float, Scalar
from scopecat.planning.routing import RoutingView
from scopecat.records.config import RoutingResource
from scopecat.sdk.instruments.contracts import CollectCommand, CollectProductRequest


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
        parameters=ParameterRelationData(),
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
                    availability=availability,
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
                    availability=availability,
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
                resource_id=physical_resource_id("source-a"),
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
                resource_id=physical_resource_id("source-b"),
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
        experiment_kind="execution_test",
        point_coordinate_ids=(),
        points=(point,),
        product_defs=(source_a_product, source_b_product),
        instrument_product_producers=(source_a_producer, source_b_producer),
        product_uses=(source_a_signal, source_b_signal),
        record_uses=(
            RecordUse(id="source-a-signal", product_use_id=source_a_signal.id),
            RecordUse(id="source-b-signal", product_use_id=source_b_signal.id),
        ),
        records=(
            BoundRecord(
                id="source-a-signal",
                product_use_id=source_a_signal.id,
                product_id=source_a_product.id,
                kind="observable",
                unit="ratio",
                dtype="float64",
                axes=(),
                dims=("point",),
                shape=(1,),
            ),
            BoundRecord(
                id="source-b-signal",
                product_use_id=source_b_signal.id,
                product_id=source_b_product.id,
                kind="observable",
                unit="ratio",
                dtype="float64",
                axes=(),
                dims=("point",),
                shape=(1,),
            ),
        ),
        route_intents=(),
        state_changes=(),
        expected_dataset_schema=None,
        compute_definitions=(
            BoundComputeDefinition(
                operation_id=producer_id,
                result=BoundComputeResult(
                    id=producer_result_id,
                    value_type=Scalar(Float()),
                    availability=availability,
                ),
            ),
            BoundComputeDefinition(
                operation_id=consumer_id,
                result=BoundComputeResult(
                    id=consumer_result_id,
                    value_type=Scalar(Float()),
                    availability=availability,
                ),
            ),
        ),
        local_implementations=local_implementations,
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

    assert [stage.kind for stage in program.points[0].stages] == [
        "compute",
        "apply_state",
        "collect",
    ]
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


def test_current_local_record_projection_rejects_unproduced_derived_use() -> None:
    program = _source_and_derived_execution_program()
    derived_use = program.product_uses[1]

    with pytest.raises(ValueError, match="require a collected product use"):
        replace(
            program,
            record_projections=(
                RecordProjection(
                    record_id="derived",
                    product_use_id=derived_use.id,
                    product_id=derived_use.product_id,
                ),
            ),
        )


def test_execution_collection_inventory_snapshots_runtime_sequence() -> None:
    program = _source_and_derived_execution_program()
    supplied = list(program.collection_product_use_ids)

    snapshotted = replace(
        program,
        collection_product_use_ids=cast(
            "tuple[ProductUseId, ...]", cast("object", supplied)
        ),
    )
    supplied.clear()

    assert snapshotted.collection_product_use_ids == (program.product_uses[0].id,)


def test_zero_point_execution_retains_nonempty_collection_inventory() -> None:
    source_use = product_use(product_id("source"))

    program = ExecutionProgram(
        experiment_id="zero-point-collection-contract",
        points=(),
        product_uses=(source_use,),
        collection_product_use_ids=(source_use.id,),
        record_projections=(),
    )

    assert program.collection_product_use_ids == (source_use.id,)


@pytest.mark.parametrize("mutation", ["duplicate", "unknown", "noncanonical"])
def test_execution_collection_inventory_rejects_invalid_identity_set(
    mutation: str,
) -> None:
    first = product_use(product_id("first"))
    second = product_use(product_id("second"))
    foreign = product_use(product_id("foreign"))
    selected = {
        "duplicate": (first.id, first.id),
        "unknown": (first.id, foreign.id),
        "noncanonical": (second.id, first.id),
    }[mutation]

    with pytest.raises(ValueError):
        ExecutionProgram(
            experiment_id="invalid-collection-contract",
            points=(),
            product_uses=(first, second),
            collection_product_use_ids=selected,
            record_projections=(),
        )


def test_each_point_must_exactly_cover_collection_inventory() -> None:
    program = _source_and_derived_execution_program()

    with pytest.raises(ValueError, match="collection product-use inventory"):
        replace(
            program,
            collection_product_use_ids=(),
            record_projections=(),
        )


def test_point_program_rejects_non_topological_compute_order() -> None:
    producer_id = OperationId(SymbolId(local_id="producer"))
    consumer_id = OperationId(SymbolId(local_id="consumer"))
    producer = ComputeOperation(
        operation_id="point.compute.producer",
        semantic_operation_id="producer",
        implementation_id="python.producer.v1",
        contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
        kernel=lambda: 1.0,
        inputs={},
        result=ComputeResultSlot(
            id=operation_result_id(producer_id),
            value_type=Scalar(Float()),
        ),
    )
    consumer = ComputeOperation(
        operation_id="point.compute.consumer",
        semantic_operation_id="consumer",
        implementation_id="python.consumer.v1",
        contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
        kernel=_identity_value,
        inputs={"value": OutputInput(producer.result.id)},
        result=ComputeResultSlot(
            id=operation_result_id(consumer_id),
            value_type=Scalar(Float()),
        ),
    )

    with pytest.raises(ValueError, match="not topologically available"):
        PointProgram(
            point_index=0,
            point_uid="point",
            coordinates={},
            stages=(ComputeStage(operations=(consumer, producer)),),
        )


def test_point_compute_order_does_not_alias_operation_and_value_namespaces() -> None:
    shared_symbol = SymbolId(local_id="shared")
    producer_id = OperationId(shared_symbol)
    producer_result_id = operation_result_id(producer_id)
    wrong_value_id = ValueId(shared_symbol)
    assert producer_id != wrong_value_id

    producer = ComputeOperation(
        operation_id=shared_symbol.qualified_name,
        semantic_operation_id=producer_id.qualified_name,
        implementation_id="python.shared.v1",
        contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
        kernel=lambda: 1.0,
        inputs={},
        result=ComputeResultSlot(
            id=producer_result_id,
            value_type=Scalar(Float()),
        ),
    )
    consumer = ComputeOperation(
        operation_id="point.compute.consumer",
        semantic_operation_id="consumer",
        implementation_id="python.consumer.v1",
        contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
        kernel=_identity_value,
        inputs={"value": OutputInput(wrong_value_id)},
        result=ComputeResultSlot(
            id=operation_result_id(OperationId(SymbolId(local_id="consumer"))),
            value_type=Scalar(Float()),
        ),
    )

    with pytest.raises(ValueError, match=r"results.*not topologically available"):
        PointProgram(
            point_index=0,
            point_uid="point",
            coordinates={},
            stages=(ComputeStage(operations=(producer, consumer)),),
        )


def test_resource_claims_are_unconditionally_exclusive() -> None:
    claim = ResourceClaim(id="source-a")

    assert claim.kind == "instrument"


def test_collect_command_attempt_is_rejected_before_execution() -> None:
    program = _source_and_derived_execution_program()
    stage = cast("CollectStage", program.points[0].stages[0])
    operation = stage.operations[0]

    with pytest.raises(ValueError, match="runtime-owned and must start at one"):
        replace(
            operation,
            command=operation.command.model_copy(update={"attempt": 2}),
        )


def test_collect_operation_snapshots_supplied_command() -> None:
    program = _source_and_derived_execution_program()
    stage = cast("CollectStage", program.points[0].stages[0])
    supplied = stage.operations[0].command
    operation = replace(stage.operations[0], command=supplied)

    supplied.metadata["mutated-after-construction"] = True

    assert operation.command.metadata == {}


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
        record_projections=(
            RecordProjection(
                record_id="source",
                product_use_id=source_use.id,
                product_id=source_use.product_id,
            ),
        ),
    )


def _gain_state(instrument_id: str, value: float) -> BoundResourceState:
    return BoundResourceState(
        resource_id=physical_resource_id(instrument_id),
        capability_id="set_gain",
        fields=(BoundStateField(field_path="gain", value=StateValue(value)),),
    )


def _identity_value(*, value: object) -> object:
    return value
