from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import cast

from scopecat.compiler.relations.context import EvalContext
from scopecat.compiler.relations.evaluation import (
    evaluate_scalar,
    evaluate_series,
)
from scopecat.compiler.relations.uses import (
    RelationUse,
    RelationUseId,
)
from scopecat.compiler.relations.verification import VerifiedRelationPlan
from scopecat.compiler.semantic.value_expressions import (
    ScalarOrSeriesValueExpr,
    ScalarValueExpr,
)
from scopecat.graph.relations.analysis import PlanNode
from scopecat.graph.relations.model import (
    CellValue,
    ScalarExpr,
    SeriesExpr,
)
from scopecat.graph.values import ComputeResultRef
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.resource_identity import (
    LogicalResourcePortId,
)

type TargetEntityValue = str | EntityRef
type RelationPlanResolver = Callable[[RelationUseId], VerifiedRelationPlan[PlanNode]]


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
    target_entity_uses: tuple[RelationUse[ScalarOrSeriesValueExpr], ...] = ()

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
    relation_plan: RelationPlanResolver,
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
                else evaluate_scalar(
                    cast(
                        "VerifiedRelationPlan[ScalarExpr]",
                        relation_plan(value_use.id),
                    ),
                    ctx,
                )
            ),
            target_entities=tuple(
                _evaluate_target_entities(
                    spec.target_entity_uses,
                    ctx,
                    relation_plan=relation_plan,
                )
            ),
        )
    ]


def _evaluate_target_entities(
    uses: Sequence[RelationUse[ScalarOrSeriesValueExpr]],
    ctx: EvalContext,
    *,
    relation_plan: RelationPlanResolver,
) -> list[TargetEntityValue]:
    evaluated: list[CellValue] = []
    for use in uses:
        expression = use.value
        if isinstance(expression, ScalarValueExpr):
            evaluated.append(
                evaluate_scalar(
                    cast(
                        "VerifiedRelationPlan[ScalarExpr]",
                        relation_plan(use.id),
                    ),
                    ctx,
                )
            )
        else:
            series_values = evaluate_series(
                cast(
                    "VerifiedRelationPlan[SeriesExpr]",
                    relation_plan(use.id),
                ),
                ctx,
            )
            if not series_values:
                msg = "state target entity series must not be empty"
                raise ValueError(msg)
            evaluated.extend(series_values)
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
