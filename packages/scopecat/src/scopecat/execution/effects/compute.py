"""Pure compute-effect evaluation and payload observation."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from pydantic import JsonValue

from scopecat.execution.effects.journaled import JournaledEffectBoundary
from scopecat.execution.events import payload_summary
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

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class EffectEvaluationStats:
    compute_evaluated_node_count: int = 0
    compute_payload_count: int = 0


@dataclass(slots=True, kw_only=True)
class EffectEvaluationFrame:
    event_point_index: int | None = None
    stats: EffectEvaluationStats = field(default_factory=EffectEvaluationStats)
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
        payload_observer: Callable[[CommandPayload], None] | None,
    ) -> None:
        self.journal = journal
        self.payload_observer = payload_observer

    def execute(
        self,
        frame: EffectEvaluationFrame,
        operations: Sequence[ComputeOperation],
    ) -> None:
        for operation in operations:
            entry = self.journal.entry(
                operation_id=operation.operation_id,
                stage="compute",
                effect="pure",
                state="started",
                point_index=frame.event_point_index,
                evidence={
                    "semantic_operation_id": operation.semantic_operation_id,
                    "implementation_id": operation.implementation_id,
                    **_dependency_summary(operation.dependencies),
                },
            )
            self.journal.observe(entry)
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
                    point_index=frame.event_point_index,
                )
                self.journal.problems.append(problem)
                self.journal.observe(
                    entry.model_copy(update={"state": "failed", "problems": (problem,)})
                )
                return
            frame.compute_results[operation.result.id] = result
            frame.stats.compute_evaluated_node_count += 1
            if operation.payload_slot is not None:
                slot = operation.payload_slot
                frame.payloads[slot.id] = CommandPayload(
                    id=slot.id,
                    schema_id=slot.schema_id,
                    content_hash=content_hash,
                    operation_id=operation.operation_id,
                    semantic_operation_id=operation.semantic_operation_id,
                    implementation_id=operation.implementation_id,
                    point_index=frame.event_point_index,
                    payload=result,
                )
                frame.stats.compute_payload_count += 1
                self._observe_payload(frame.payloads[slot.id])
            self.journal.observe(
                entry.model_copy(
                    update={
                        "state": "completed",
                        "evidence": {
                            "semantic_operation_id": operation.semantic_operation_id,
                            "implementation_id": operation.implementation_id,
                            **_dependency_summary(operation.dependencies),
                            **(
                                {
                                    "payload_id": operation.payload_slot.id,
                                    "schema_id": operation.payload_slot.schema_id,
                                    "content_hash": content_hash,
                                    **payload_summary(result),
                                }
                                if operation.payload_slot is not None
                                else {}
                            ),
                        },
                    }
                )
            )

    def _observe_payload(self, payload: CommandPayload) -> None:
        if self.payload_observer is None:
            return
        try:
            self.payload_observer(payload)
        except BaseException:
            logger.exception(
                "execution payload observer failed",
                extra={"run_id": self.journal.run_id, "payload_id": payload.id},
            )


def _dependency_summary(
    dependencies: Mapping[str, tuple[str, ...]],
) -> dict[str, JsonValue]:
    if not dependencies:
        return {}
    return {
        "dependencies": {name: list(values) for name, values in dependencies.items()}
    }
