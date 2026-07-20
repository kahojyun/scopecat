from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import cast

from scopecat.compiler.relations.analysis import PlanNode
from scopecat.compiler.relations.evaluation import (
    EvalContext,
    evaluate_relation_in_context,
    evaluate_scalar,
    evaluate_series,
)
from scopecat.compiler.relations.model import (
    CellValue,
    RelationExpr,
    RowScopeId,
    ScalarExpr,
    SeriesExpr,
)
from scopecat.compiler.relations.uses import (
    RelationUse,
    RelationUseId,
)
from scopecat.compiler.relations.verification import VerifiedRelationPlan
from scopecat.compiler.semantic.compute_result import ComputeResultRef
from scopecat.compiler.semantic.value_expressions import (
    ScalarOrSeriesValueExpr,
    ScalarValueExpr,
    TableValueExpr,
)
from scopecat.kernel.problems import ModelLocation, model_location
from scopecat.kernel.resource_identity import (
    LogicalResourcePortId,
)
from scopecat.records.entity import EntityRef

type TargetEntityValue = str | EntityRef
type RelationPlanResolver = Callable[[RelationUseId], VerifiedRelationPlan[PlanNode]]


type StateValueUse = RelationUse[ScalarValueExpr] | ComputeResultRef
type EvaluatedStateValue = ComputeResultRef | CellValue


@dataclass(frozen=True, slots=True)
class LogicalStateResourceTarget:
    """State target resolved through one declared logical resource port."""

    port_id: LogicalResourcePortId


class StateSpec:
    """Base class for desired-state bindings."""

    __slots__ = ()


@dataclass(frozen=True, slots=True)
class SetStateSpec(StateSpec):
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
class ForEachStateSpec(StateSpec):
    """Evaluate child state bindings for every row of one relation."""

    relation_use: RelationUse[TableValueExpr]
    state: tuple[StateSpecVariant, ...]
    row_scope_id: RowScopeId | None = None


type StateSpecVariant = SetStateSpec | ForEachStateSpec


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
    spec: StateSpecVariant,
    *,
    point_index: int,
    ctx: EvalContext,
    relation_plan: RelationPlanResolver,
    location: ModelLocation,
) -> list[StateRecord]:
    """Materialize one data-only state plan."""

    if isinstance(spec, SetStateSpec):
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
    records: list[StateRecord] = []
    relation_ctx = EvalContext(
        params=ctx.params,
        row=None,
        outer_row=ctx.row if ctx.row is not None else ctx.outer_row,
        point_row=ctx.point_row,
        row_scopes=ctx.row_scopes,
        inputs=ctx.inputs,
    )
    relation_use = spec.relation_use
    for row in evaluate_relation_in_context(
        cast(
            "VerifiedRelationPlan[RelationExpr]",
            relation_plan(relation_use.id),
        ),
        relation_ctx,
    ):
        child_ctx = EvalContext(
            params=ctx.params,
            row=row,
            outer_row=ctx.row if ctx.row is not None else ctx.outer_row,
            point_row=ctx.point_row,
            row_scopes={
                **ctx.row_scopes,
                **({spec.row_scope_id: row} if spec.row_scope_id is not None else {}),
            },
            inputs=ctx.inputs,
        )
        for child_index, child in enumerate(spec.state):
            records.extend(
                evaluate_state_spec(
                    child,
                    point_index=point_index,
                    ctx=child_ctx,
                    relation_plan=relation_plan,
                    location=model_location(
                        location.root,
                        *location.path,
                        "state",
                        child_index,
                    ),
                )
            )
    return records


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
