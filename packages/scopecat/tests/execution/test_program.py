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
    CollectionResultBinding,
    CollectOperation,
    ComputeOperation,
    ComputeResultSlot,
    OutputInput,
    StateTarget,
)
from scopecat.kernel.point_identity import LogicalPointId, PointDomainId
from scopecat.kernel.product_identity import ProductUse, product_id, product_use
from scopecat.kernel.resource_identity import ResourceClaim
from scopecat.kernel.state import StateValue
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import Float, Scalar
from scopecat.measurements.results import MeasurementDType
from scopecat.sdk.instruments.contracts import CollectCommand, CollectProductRequest
from tests.testkit.local_materialization import (
    MaterializedLocalEffects,
    MaterializedPointEffects,
)


def test_execution_program_has_explicit_ordered_effects() -> None:
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
    plan = MaterializedLocalEffects(
        points=(
            MaterializedPointEffects(
                point_index=0,
                logical_id=LogicalPointId(PointDomainId("test-program", "root"), 0),
                coordinates={},
                operations=(
                    *compute_operations,
                    *state_operations,
                    *collect_operations,
                ),
            ),
        ),
        resource_order=("source-b", "source-a"),
        resource_claims=(
            ResourceClaim("source-b"),
            ResourceClaim("source-a"),
        ),
    )

    program = plan

    operations = program.points[0].operations
    compute = tuple(
        operation for operation in operations if isinstance(operation, ComputeOperation)
    )
    state = tuple(
        operation
        for operation in operations
        if isinstance(operation, ApplyStateOperation)
    )
    collect = tuple(
        operation for operation in operations if isinstance(operation, CollectOperation)
    )
    assert [operation.semantic_operation_id for operation in compute] == [
        "produce",
        "consume",
    ]
    assert [operation.implementation_id for operation in compute] == [
        "python.produce.v1",
        "python.consume.v1",
    ]
    assert compute[1].inputs["value"] == OutputInput(producer_result_id)
    assert compute[0].result.id == producer_result_id
    assert compute[1].result.id == consumer_result_id
    assert [operation.instrument_id for operation in state] == [
        "source-b",
        "source-a",
    ]
    assert [operation.instrument_id for operation in collect] == [
        "source-b",
        "source-a",
    ]
    assert all(
        operation.command.operation_id == operation.operation_id
        for operation in collect
    )
    assert program.resource_order == ("source-b", "source-a")
    assert [claim.id for claim in program.resource_claims] == [
        "source-b",
        "source-a",
    ]


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
