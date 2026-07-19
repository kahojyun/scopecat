from __future__ import annotations

from dataclasses import replace

from scopecat.compiler.semantic.model import (
    OperationId,
    operation_result_id,
)
from scopecat.compiler.semantic.operation_contract import (
    LOCAL_OPAQUE_OPERATION_CONTRACT,
)
from scopecat.compiler.typed.products import ProductDef
from scopecat.execution.local.program import (
    ApplyStateOperation,
    ApplyStateStage,
    CollectionResultBinding,
    CollectOperation,
    CollectStage,
    ComputeOperation,
    ComputeResultSlot,
    ComputeStage,
    OutputInput,
    PointProgram,
    StateTarget,
)
from scopecat.kernel.point_identity import LogicalPointId, PointDomainId
from scopecat.kernel.product_identity import ProductUse, product_id, product_use
from scopecat.kernel.resource_identity import ResourceClaim
from scopecat.kernel.state import StateValue
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import Float, Scalar
from scopecat.measurements.results import MeasurementDType
from scopecat.planning.local_materialization import MaterializedLocalEffects
from scopecat.sdk.instruments.contracts import CollectCommand, CollectProductRequest
from tests.testkit.local_effect_program import (
    StubLocalEffectProgram,
    make_test_local_effect_program,
)


def test_execution_program_has_explicit_ordered_effect_stages() -> None:
    producer_id = OperationId(SymbolId(local_id="produce"))
    consumer_id = OperationId(SymbolId(local_id="consume"))
    producer_result_id = operation_result_id(producer_id)
    consumer_result_id = operation_result_id(consumer_id)

    def produce() -> float:
        return 1.0

    def consume(*, value: float) -> float:
        return value + 1.0

    source_a_product = ProductDef(
        id=product_id("source-a-signal"),
        unit="ratio",
        dtype="float64",
    )
    source_b_product = replace(
        source_a_product,
        id=product_id("source-b-signal"),
    )
    source_a_signal = product_use(source_a_product.id)
    source_b_signal = product_use(source_b_product.id)
    compute_operations = (
        ComputeOperation(
            operation_id="test-program:root:0.compute.produce",
            semantic_operation_id=producer_id.qualified_name,
            implementation_id="python.produce.v1",
            contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
            kernel=produce,
            inputs={},
            result=ComputeResultSlot(
                id=producer_result_id,
                value_type=Scalar(Float()),
            ),
        ),
        ComputeOperation(
            operation_id="test-program:root:0.compute.consume",
            semantic_operation_id=consumer_id.qualified_name,
            implementation_id="python.consume.v1",
            contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
            kernel=consume,
            inputs={"value": OutputInput(producer_result_id)},
            result=ComputeResultSlot(
                id=consumer_result_id,
                value_type=Scalar(Float()),
            ),
        ),
    )
    state_operations = (
        _gain_state("source-b", 2.0),
        _gain_state("source-a", 1.0),
    )
    collect_operations = (
        _collect_operation(
            "source-b",
            product_use=source_b_signal,
            provider_key="signal",
            capability="scalar_signal",
            unit="ratio",
            dtype="float64",
        ),
        _collect_operation(
            "source-a",
            product_use=source_a_signal,
            provider_key="signal",
            capability="scalar_signal",
            unit="ratio",
            dtype="float64",
        ),
    )
    point = PointProgram(
        point_index=0,
        logical_id=LogicalPointId(PointDomainId("test-program", "root"), 0),
        coordinates={},
        stages=(
            ComputeStage(compute_operations),
            ApplyStateStage(state_operations),
            CollectStage(collect_operations),
        ),
    )
    plan = MaterializedLocalEffects(
        points=(point,),
        resource_order=("source-b", "source-a"),
        resource_claims=(
            ResourceClaim("source-b"),
            ResourceClaim("source-a"),
        ),
    )

    program = make_test_local_effect_program(
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
    assert set(program.collection_product_use_ids) == {
        source_a_signal.id,
        source_b_signal.id,
    }
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

    program = StubLocalEffectProgram(
        experiment_id="zero-point-collection-contract",
        points=(),
        product_uses=(source_use,),
        collection_product_use_ids=(source_use.id,),
        resource_order=(),
        resource_claims=(),
    )

    assert program.collection_product_use_ids == (source_use.id,)


def _source_and_derived_execution_program() -> StubLocalEffectProgram:
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
    return StubLocalEffectProgram(
        experiment_id="source-and-derived",
        points=(
            PointProgram(
                point_index=0,
                logical_id=LogicalPointId(PointDomainId("source-derived", "root"), 0),
                coordinates={},
                stages=(CollectStage(operations=(collect,)),),
            ),
        ),
        product_uses=(source_use, derived_use),
        collection_product_use_ids=(source_use.id,),
        resource_order=("source-0",),
        resource_claims=(ResourceClaim(id="source-0"),),
    )


def _gain_state(instrument_id: str, value: float) -> ApplyStateOperation:
    return ApplyStateOperation(
        operation_id=f"point.state.{instrument_id}",
        instrument_id=instrument_id,
        targets=(
            StateTarget(
                capability_id="set_gain",
                field_path="gain",
                value=StateValue(value),
            ),
        ),
    )


def _collect_operation(
    instrument_id: str,
    *,
    product_use: ProductUse,
    provider_key: str,
    capability: str,
    unit: str,
    dtype: MeasurementDType,
) -> CollectOperation:
    operation_id = f"point.collect.{instrument_id}"
    return CollectOperation(
        operation_id=operation_id,
        instrument_id=instrument_id,
        command=CollectCommand(
            operation_id=operation_id,
            instrument_id=instrument_id,
            point_index=0,
            point_count=1,
            requests=[
                CollectProductRequest(
                    id=provider_key,
                    capability_id=capability,
                    unit=unit,
                    dtype=dtype,
                )
            ],
        ),
        result_bindings=(
            CollectionResultBinding(
                provider_key=provider_key,
                product_use_id=product_use.id,
                product_id=product_use.product_id,
            ),
        ),
    )
