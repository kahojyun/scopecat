from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from scopecat.compiler.relations.context import EvalContext
from scopecat.compiler.relations.evaluation import (
    evaluate_scalar,
)
from scopecat.compiler.relations.uses import RelationUse
from scopecat.compiler.semantic.value_expressions import (
    ScalarValueExpr,
)
from scopecat.graph.relations.model import (
    CellValue,
)
from scopecat.graph.values import ComputeResultRef
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.resource_identity import (
    LogicalResourcePortId,
)

type TargetEntityValue = str | EntityRef


type StateValueUse = RelationUse[ScalarValueExpr] | ComputeResultRef
type EvaluatedStateValue = ComputeResultRef | CellValue


@dataclass(frozen=True, slots=True)
class LogicalStateResourceTarget:
    """State target resolved through one declared logical resource port."""

    port_id: LogicalResourcePortId


@dataclass(frozen=True, slots=True)
class SetStateSpec:
    """Assign one capability field after point-local parameter overlays."""

    resource_target: LogicalStateResourceTarget
    capability_id: str
    field_path: str
    value_use: StateValueUse
    target_entity_uses: tuple[RelationUse[ScalarValueExpr], ...] = ()

    @property
    def field(self) -> str:
        return f"{self.capability_id}.{self.field_path}"


@dataclass(frozen=True, slots=True)
class StateRecord:
    point_index: int
    resource_target: LogicalResourcePortId
    capability_id: str
    field_path: str
    value: EvaluatedStateValue
    target_entities: tuple[TargetEntityValue, ...] = ()

    @property
    def field(self) -> str:
        return f"{self.capability_id}.{self.field_path}"


def evaluate_state_spec(
    spec: SetStateSpec,
    *,
    point_index: int,
    ctx: EvalContext,
) -> list[StateRecord]:
    """Materialize one data-only state plan."""

    value_use = spec.value_use
    return [
        StateRecord(
            point_index=point_index,
            resource_target=spec.resource_target.port_id,
            capability_id=spec.capability_id,
            field_path=spec.field_path,
            value=(
                value_use
                if isinstance(value_use, ComputeResultRef)
                else evaluate_scalar(value_use.value.plan, ctx)
            ),
            target_entities=tuple(
                _evaluate_target_entities(
                    spec.target_entity_uses,
                    ctx,
                )
            ),
        )
    ]


def _evaluate_target_entities(
    uses: Sequence[RelationUse[ScalarValueExpr]],
    ctx: EvalContext,
) -> list[TargetEntityValue]:
    evaluated: list[CellValue] = [evaluate_scalar(use.value.plan, ctx) for use in uses]
    entities: list[TargetEntityValue] = []
    seen_ids: set[str] = set()
    for value in evaluated:
        if isinstance(value, EntityRef):
            entity_id = value.id
        elif isinstance(value, str) and value:
            entity_id = value
        else:
            msg = (
                "state target entity must resolve to an entity reference, "
                f"got {value!r}"
            )
            raise TypeError(msg)
        if not entity_id:
            msg = "state target entity id must be non-empty"
            raise ValueError(msg)
        if entity_id in seen_ids:
            continue
        seen_ids.add(entity_id)
        entities.append(value)
    return entities
