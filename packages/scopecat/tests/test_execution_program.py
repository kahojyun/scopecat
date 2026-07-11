from __future__ import annotations

import pytest

from scopecat._compiler.bound import (
    BoundCollect,
    BoundComputeCall,
    BoundComputeOutput,
    BoundPlan,
    BoundPoint,
    BoundProduct,
    BoundRecord,
    BoundResourceState,
    BoundStateField,
)
from scopecat._compiler.ids import NodeId
from scopecat._execution.lowering import build_execution_program
from scopecat._execution.program import (
    ApplyStateStage,
    CollectStage,
    ComputeOperation,
    ComputeStage,
    OutputInput,
    PointProgram,
    ResourceClaim,
)
from scopecat._relations import ParameterRelationData
from scopecat.models.state import StateValue
from scopecat.value_types import Float, Scalar


def test_execution_program_has_explicit_ordered_effect_stages() -> None:
    producer_id = NodeId(local_id="produce")
    consumer_id = NodeId(local_id="consume")
    point = BoundPoint(
        point_index=0,
        point_key="point-key",
        point_uid="point-uid",
        occurrence=0,
        row={},
        parameters=ParameterRelationData(),
        coordinates={},
        compute=(
            BoundComputeCall(
                node_id=producer_id,
                fn=lambda: 1.0,
                inputs={},
                output_type=Scalar(Float()),
                cache_key="producer-key",
            ),
            BoundComputeCall(
                node_id=consumer_id,
                fn=lambda *, value: value + 1.0,
                inputs={"value": BoundComputeOutput(producer_id)},
                output_type=Scalar(Float()),
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
                instrument_id=None,
                products=(
                    BoundProduct(
                        record_id="signal",
                        instrument_id=None,
                        product_key="signal",
                        kind="observable",
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
        records=(
            BoundRecord(
                id="signal",
                kind="observable",
                source="instrument",
                resource=None,
                capability="scalar_signal",
                product_key="signal",
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
    )

    program = build_execution_program(
        plan,
        instrument_order=("source-b", "source-a"),
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
    assert [operation.kernel_id for operation in compute.operations] == [
        "produce",
        "consume",
    ]
    assert compute.operations[1].inputs["value"] == OutputInput(
        compute.operations[0].operation_id
    )
    assert [operation.instrument_id for operation in state.operations] == [
        "source-b",
        "source-a",
    ]
    assert [operation.instrument_id for operation in collect.operations] == [
        "source-b",
        "source-a",
    ]
    assert all(
        operation.command.operation_id == operation.operation_id
        for operation in collect.operations
    )
    assert program.resource_order == ("source-b", "source-a")


def test_point_program_rejects_non_topological_compute_order() -> None:
    producer = ComputeOperation(
        operation_id="point.compute.producer",
        kernel_id="producer",
        kernel=lambda: 1.0,
        inputs={},
        output_type=Scalar(Float()),
    )
    consumer = ComputeOperation(
        operation_id="point.compute.consumer",
        kernel_id="consumer",
        kernel=lambda *, value: value,
        inputs={"value": OutputInput(producer.operation_id)},
        output_type=Scalar(Float()),
    )

    with pytest.raises(ValueError, match="not topologically available"):
        PointProgram(
            point_index=0,
            point_uid="point",
            coordinates={},
            stages=(ComputeStage(operations=(consumer, producer)),),
        )


def test_resource_claims_are_unconditionally_exclusive() -> None:
    claim = ResourceClaim(id="source-a")

    assert claim.kind == "instrument"
    assert not hasattr(claim, "exclusive")


def _gain_state(instrument_id: str, value: float) -> BoundResourceState:
    return BoundResourceState(
        resource_id=instrument_id,
        capability_id="set_gain",
        fields=(BoundStateField(field_path="gain", value=StateValue(value)),),
    )
