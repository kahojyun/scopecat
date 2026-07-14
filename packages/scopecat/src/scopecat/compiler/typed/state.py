from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal, cast

from scopecat.compiler.relations.analysis import PlanNode
from scopecat.compiler.relations.backend import (
    EvalContext,
    RelationBackend,
    SelectedRelationPlan,
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
from scopecat.kernel.value_types import String
from scopecat.records.entity import EntityRef

type StateSpecKind = Literal["set", "for_each"]
type RouteEntityValue = str | EntityRef
type SelectedPlanResolver = Callable[[RelationUseId], SelectedRelationPlan[PlanNode]]


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

    def __post_init__(self) -> None:
        if not isinstance(self.use.value.value_type.atom, String):
            msg = "physical state resource targets require a string scalar relation"
            raise ValueError(msg)


type StateResourceTarget = LogicalStateResourceTarget | PhysicalStateResourceTarget


@dataclass(frozen=True, slots=True)
class StateSpec:
    """Desired-state binding evaluated after point-local parameter overlays."""

    kind: StateSpecKind
    resource_target: StateResourceTarget | None = None
    capability_id: str | None = None
    field_path: str | None = None
    value_use: StateValueUse | None = None
    route_entity_uses: tuple[RelationUse[ScalarOrSeriesValueExpr], ...] = ()
    relation_use: RelationUse[TableValueExpr] | None = None
    row_scope_id: RowScopeId | None = None
    state: tuple[StateSpec, ...] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "route_entity_uses", tuple(self.route_entity_uses))
        if self.state is not None:
            object.__setattr__(self, "state", tuple(self.state))
        if self.capability_id == "" or self.field_path == "":
            msg = "state capability id and field path must be non-empty when present"
            raise ValueError(msg)
        if self.kind == "set":
            if (
                self.resource_target is None
                or self.capability_id is None
                or self.field_path is None
                or self.value_use is None
            ):
                msg = "set state requires resource, capability, field path, and value"
                raise ValueError(msg)
            self._reject("relation_use", "row_scope_id", "state")
        elif self.kind == "for_each":
            if self.relation_use is None or not self.state:
                msg = "for_each state requires relation and state"
                raise ValueError(msg)
            self._reject(
                "resource_target",
                "capability_id",
                "field_path",
                "value_use",
                "route_entity_uses",
            )
        else:
            msg = f"unsupported state kind: {self.kind!r}"
            raise ValueError(msg)

    @property
    def field(self) -> str | None:
        if self.capability_id is None or self.field_path is None:
            return None
        return f"{self.capability_id}.{self.field_path}"

    def _reject(self, *field_names: str) -> None:
        unexpected = [
            field_name
            for field_name in field_names
            if _is_present(getattr(self, field_name))
        ]
        if unexpected:
            msg = f"{self.kind} state cannot contain: {', '.join(unexpected)}"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class StateRecord:
    point_index: int
    resource_target: ResourceTarget
    capability_id: str
    field_path: str
    value: EvaluatedStateValue
    route_entities: tuple[RouteEntityValue, ...] = ()

    def __post_init__(self) -> None:
        if self.point_index < 0 or not self.capability_id or not self.field_path:
            msg = "state records require nonnegative points and non-empty field ids"
            raise ValueError(msg)
        object.__setattr__(self, "route_entities", tuple(self.route_entities))

    @property
    def field(self) -> str:
        return f"{self.capability_id}.{self.field_path}"


def evaluate_state_spec(
    spec: StateSpec,
    *,
    point_index: int,
    ctx: EvalContext,
    backend: RelationBackend,
    selected_plan: SelectedPlanResolver,
    location: ModelLocation,
) -> list[StateRecord]:
    """Materialize one data-only state plan with the selected backend."""

    if spec.kind == "set":
        resource_target = _required(spec.resource_target)
        resource = (
            resource_target.port_id
            if isinstance(resource_target, LogicalStateResourceTarget)
            else PhysicalResourceId(
                _evaluate_physical_resource(
                    resource_target.use,
                    ctx,
                    backend=backend,
                    selected_plan=selected_plan,
                )
            )
        )
        value_use = _required(spec.value_use)
        return [
            StateRecord(
                point_index=point_index,
                resource_target=resource,
                capability_id=_required(spec.capability_id),
                field_path=_required(spec.field_path),
                value=(
                    value_use
                    if isinstance(value_use, ComputeResultRef)
                    else evaluate_scalar(
                        backend,
                        cast(
                            "SelectedRelationPlan[ScalarExpr]",
                            selected_plan(value_use.id),
                        ),
                        ctx,
                    )
                ),
                route_entities=tuple(
                    _evaluate_route_entities(
                        spec.route_entity_uses,
                        ctx,
                        backend=backend,
                        selected_plan=selected_plan,
                    )
                ),
            )
        ]
    if spec.kind == "for_each":
        records: list[StateRecord] = []
        relation_ctx = EvalContext(
            params=ctx.params,
            row=None,
            outer_row=ctx.row if ctx.row is not None else ctx.outer_row,
            point_row=ctx.point_row,
            row_scopes=ctx.row_scopes,
            inputs=ctx.inputs,
        )
        relation_use = _required(spec.relation_use)
        for row in evaluate_relation_in_context(
            backend,
            cast(
                "SelectedRelationPlan[RelationExpr]",
                selected_plan(relation_use.id),
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
                    **(
                        {spec.row_scope_id: row}
                        if spec.row_scope_id is not None
                        else {}
                    ),
                },
                inputs=ctx.inputs,
            )
            for child_index, child in enumerate(_required(spec.state)):
                records.extend(
                    evaluate_state_spec(
                        child,
                        point_index=point_index,
                        ctx=child_ctx,
                        backend=backend,
                        selected_plan=selected_plan,
                        location=model_location(
                            location.root,
                            *location.path,
                            "state",
                            child_index,
                        ),
                    )
                )
        return records
    msg = f"unsupported state spec kind: {spec.kind}"
    raise ValueError(msg)


def _evaluate_physical_resource(
    use: RelationUse[ScalarValueExpr],
    ctx: EvalContext,
    *,
    backend: RelationBackend,
    selected_plan: SelectedPlanResolver,
) -> str:
    value = evaluate_scalar(
        backend,
        cast(
            "SelectedRelationPlan[ScalarExpr]",
            selected_plan(use.id),
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


def _required[T](value: T | None) -> T:
    if value is None:
        raise AssertionError("validated field is unexpectedly missing")
    return value


def _evaluate_route_entities(
    uses: Sequence[RelationUse[ScalarOrSeriesValueExpr]],
    ctx: EvalContext,
    *,
    backend: RelationBackend,
    selected_plan: SelectedPlanResolver,
) -> list[RouteEntityValue]:
    evaluated: list[CellValue] = []
    for use in uses:
        expression = use.value
        if isinstance(expression, ScalarValueExpr):
            evaluated.append(
                evaluate_scalar(
                    backend,
                    cast(
                        "SelectedRelationPlan[ScalarExpr]",
                        selected_plan(use.id),
                    ),
                    ctx,
                )
            )
        else:
            series_values = evaluate_series(
                backend,
                cast(
                    "SelectedRelationPlan[SeriesExpr]",
                    selected_plan(use.id),
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


def _is_present(value: object) -> bool:
    if value is None:
        return False
    return not (isinstance(value, list | tuple) and not value)


__all__ = [
    "EvaluatedStateValue",
    "LogicalStateResourceTarget",
    "PhysicalStateResourceTarget",
    "StateRecord",
    "StateResourceTarget",
    "StateSpec",
    "StateSpecKind",
    "StateValueUse",
    "evaluate_state_spec",
]
