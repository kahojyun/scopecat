from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Literal, cast

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
    PhysicalResourceId,
    ResourceTarget,
)
from scopecat.records.entity import EntityRef

type RouteEntityValue = str | EntityRef
type RelationPlanResolver = Callable[[RelationUseId], VerifiedRelationPlan[PlanNode]]


type StateValueUse = RelationUse[ScalarValueExpr] | ComputeResultRef
type EvaluatedStateValue = ComputeResultRef | CellValue


@dataclass(frozen=True, slots=True)
class LogicalStateResourceTarget:
    """State target resolved through one declared logical resource port."""

    port_id: LogicalResourcePortId
    kind: Literal["logical_port"] = "logical_port"


@dataclass(frozen=True, slots=True)
class PhysicalStateResourceTarget:
    """State target whose physical identity is computed by a relation."""

    use: RelationUse[ScalarValueExpr]
    kind: Literal["physical_relation"] = "physical_relation"


type StateResourceTarget = LogicalStateResourceTarget | PhysicalStateResourceTarget


class StateSpec:
    """Base class for desired-state bindings."""

    __slots__ = ()


@dataclass(frozen=True, slots=True)
class SetStateSpec(StateSpec):
    """Assign one capability field after point-local parameter overlays."""

    resource_target: StateResourceTarget
    capability_id: str
    field_path: str
    value_use: StateValueUse
    route_entity_uses: tuple[RelationUse[ScalarOrSeriesValueExpr], ...] = ()
    kind: Literal["set"] = field(default="set", init=False)

    @property
    def field(self) -> str:
        return f"{self.capability_id}.{self.field_path}"


@dataclass(frozen=True, slots=True)
class ForEachStateSpec(StateSpec):
    """Evaluate child state bindings for every row of one relation."""

    relation_use: RelationUse[TableValueExpr]
    state: tuple[StateSpecVariant, ...]
    row_scope_id: RowScopeId | None = None
    kind: Literal["for_each"] = field(default="for_each", init=False)


type StateSpecVariant = SetStateSpec | ForEachStateSpec


@dataclass(frozen=True, slots=True)
class StateRecord:
    point_index: int
    resource_target: ResourceTarget
    capability_id: str
    field_path: str
    value: EvaluatedStateValue
    route_entities: tuple[RouteEntityValue, ...] = ()

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
        resource_target = spec.resource_target
        resource = (
            resource_target.port_id
            if isinstance(resource_target, LogicalStateResourceTarget)
            else PhysicalResourceId(
                _evaluate_physical_resource(
                    resource_target.use,
                    ctx,
                    relation_plan=relation_plan,
                )
            )
        )
        value_use = spec.value_use
        return [
            StateRecord(
                point_index=point_index,
                resource_target=resource,
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
                route_entities=tuple(
                    _evaluate_route_entities(
                        spec.route_entity_uses,
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


def _evaluate_physical_resource(
    use: RelationUse[ScalarValueExpr],
    ctx: EvalContext,
    *,
    relation_plan: RelationPlanResolver,
) -> str:
    value = evaluate_scalar(
        cast(
            "VerifiedRelationPlan[ScalarExpr]",
            relation_plan(use.id),
        ),
        ctx,
    )
    if not isinstance(value, str):
        msg = f"physical state resource must resolve to string, got {value!r}"
        raise TypeError(msg)
    if not value:
        msg = "physical state resource id must be non-empty"
        raise ValueError(msg)
    return value


def _evaluate_route_entities(
    uses: Sequence[RelationUse[ScalarOrSeriesValueExpr]],
    ctx: EvalContext,
    *,
    relation_plan: RelationPlanResolver,
) -> list[RouteEntityValue]:
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
                msg = "state route entity series must not be empty"
                raise ValueError(msg)
            evaluated.extend(series_values)
    entities: list[RouteEntityValue] = []
    seen_ids: set[str] = set()
    for value in evaluated:
        if isinstance(value, EntityRef):
            entity_id = value.id
        elif isinstance(value, str) and value:
            entity_id = value
        else:
            msg = (
                f"state route entity must resolve to an entity reference, got {value!r}"
            )
            raise TypeError(msg)
        if not entity_id:
            msg = "state route entity id must be non-empty"
            raise ValueError(msg)
        if entity_id in seen_ids:
            continue
        seen_ids.add(entity_id)
        entities.append(value)
    return entities
