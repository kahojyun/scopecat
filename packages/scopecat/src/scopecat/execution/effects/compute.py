"""Pure compute-effect evaluation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from scopecat.execution.effects.journaled import JournaledEffectBoundary
from scopecat.execution.local.program import (
    BoundInput,
    ComputeOperation,
)
from scopecat.graph.values import ValueId
from scopecat.kernel.content_identity import (
    content_fingerprint,
    stable_content_hash,
)
from scopecat.kernel.payloads import unwrap_payload_values
from scopecat.kernel.point_identity import LogicalPointId
from scopecat.kernel.product_identity import ProductUseId
from scopecat.kernel.value_validation import coerce_literal
from scopecat.records.artifact import CommandPayload


@dataclass(slots=True, kw_only=True)
class EffectEvaluationFrame:
    compute_results: dict[ValueId, object] = field(default_factory=dict)
    payloads: dict[str, CommandPayload] = field(default_factory=dict)


@dataclass(slots=True)
class PointEffectState(EffectEvaluationFrame):
    point_index: int
    logical_id: LogicalPointId
    product_use_ids: set[ProductUseId] = field(default_factory=set)


class ComputeEffectExecutor:
    """Evaluate closed compute nodes and retain their normalized outputs."""

    def __init__(
        self,
        *,
        journal: JournaledEffectBoundary,
    ) -> None:
        self.journal = journal

    def execute(
        self,
        frame: EffectEvaluationFrame,
        operations: Sequence[ComputeOperation],
    ) -> None:
        for operation in operations:
            try:
                inputs = {
                    name: (
                        value.value
                        if isinstance(value, BoundInput)
                        else frame.compute_results[value.value_id]
                    )
                    for name, value in operation.inputs.items()
                }
                raw_result = operation.kernel(**inputs)
                result = unwrap_payload_values(
                    coerce_literal(
                        operation.result.value_type,
                        raw_result,
                        path=("operations", operation.operation_id, "output"),
                    )
                )
                if operation.payload_slot is not None:
                    fingerprint = content_fingerprint(result)
                    content_hash = stable_content_hash(fingerprint)
                else:
                    content_hash = None
            except Exception as error:
                problem = self.journal.problem_from_exception(
                    "compute_operation_failed",
                    f"compute operation {operation.operation_id} failed",
                    error,
                    operation_id=operation.operation_id,
                    point_index=(
                        frame.point_index
                        if isinstance(frame, PointEffectState)
                        else None
                    ),
                )
                self.journal.problems.append(problem)
                return
            frame.compute_results[operation.result.id] = result
            if operation.payload_slot is not None:
                slot = operation.payload_slot
                frame.payloads[slot.id] = CommandPayload(
                    id=slot.id,
                    schema_id=slot.schema_id,
                    content_hash=content_hash,
                    operation_id=operation.operation_id,
                    semantic_operation_id=operation.semantic_operation_id,
                    implementation_id=operation.implementation_id,
                    point_index=(
                        frame.point_index
                        if isinstance(frame, PointEffectState)
                        else None
                    ),
                    payload=result,
                )
