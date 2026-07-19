"""Test-only local effect programs for focused interpreter unit tests."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from scopecat.execution.local.program import (
    CollectStage,
    PointProgram,
)
from scopecat.execution.program import (
    RunOperation,
    RunPointEnd,
    RunPointStage,
    run_point_start,
)
from scopecat.kernel.product_identity import ProductUse, ProductUseId
from scopecat.kernel.resource_identity import ResourceClaim
from scopecat.planning.local_materialization import MaterializedLocalEffects


@dataclass(frozen=True, slots=True)
class StubLocalEffectProgram:
    """Minimal structural program used where a full RunProgram is irrelevant."""

    experiment_id: str
    points: tuple[PointProgram, ...]
    product_uses: tuple[ProductUse, ...]
    collection_product_use_ids: tuple[ProductUseId, ...]
    resource_order: tuple[str, ...]
    resource_claims: tuple[ResourceClaim, ...]

    @property
    def point_count(self) -> int:
        return len(self.points)


def complete_point_operations(
    program: StubLocalEffectProgram,
) -> tuple[RunOperation, ...]:
    return tuple(
        operation
        for point in program.points
        for operation in (
            run_point_start(point),
            *(RunPointStage(point.point_index, stage) for stage in point.stages),
            RunPointEnd(point.point_index),
        )
    )


def make_test_local_effect_program(
    local_execution: MaterializedLocalEffects,
    *,
    instrument_order: Sequence[str],
) -> StubLocalEffectProgram:
    requested_order = tuple(instrument_order)
    selected_requested_order = tuple(
        instrument_id
        for instrument_id in requested_order
        if instrument_id in local_execution.resource_order
    )
    if requested_order and selected_requested_order != local_execution.resource_order:
        msg = "test program must be materialized with the requested instrument order"
        raise ValueError(msg)
    points = local_execution.points
    product_uses = local_execution.product_uses
    collected_product_use_ids = {
        binding.product_use_id
        for point in points
        for stage in point.stages
        if isinstance(stage, CollectStage)
        for operation in stage.operations
        for binding in operation.result_bindings
    }
    return StubLocalEffectProgram(
        experiment_id=local_execution.experiment_id,
        points=points,
        product_uses=product_uses,
        collection_product_use_ids=tuple(
            use.id for use in product_uses if use.id in collected_product_use_ids
        ),
        resource_order=local_execution.resource_order,
        resource_claims=local_execution.resource_claims,
    )
