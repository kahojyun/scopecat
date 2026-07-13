from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Annotated, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scopecat._compiler.problems import compiler_problem
from scopecat._compute_result import ComputeResultRef
from scopecat._relations import (
    CellValue,
    EvalContext,
    RelationExpr,
    ScalarExpr,
    SeriesExpr,
    as_scalar_expr,
    values,
)
from scopecat._value_expressions import (
    ScalarOrSeriesValueExpr,
    ScalarValueExpr,
    SeriesValueExpr,
    TableValueExpr,
    as_scalar_or_series_value_expr,
)
from scopecat.models.entity import EntityRef
from scopecat.problems import Problem, ProblemCategory, model_location

type StateSpecKind = Literal["set", "for_each"]
type RouteEntityValue = str | EntityRef


type StateValueExpr = ScalarExpr | ComputeResultRef
type EvaluatedStateValue = Annotated[
    ComputeResultRef | CellValue,
    Field(union_mode="left_to_right"),
]


class StateSpec(BaseModel):
    """Desired-state binding evaluated after point-local parameter overlays."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    kind: StateSpecKind
    resource: ScalarExpr | None = None
    capability_id: str | None = Field(default=None, min_length=1)
    field_path: str | None = Field(default=None, min_length=1)
    value: StateValueExpr | None = None
    route_entities: list[ScalarOrSeriesValueExpr] = Field(default_factory=list)
    relation: RelationExpr | None = None
    state: list[StateSpec] | None = None

    @field_validator("route_entities", mode="before")
    @classmethod
    def coerce_route_entities(cls, value: object) -> object:
        if not isinstance(value, list | tuple):
            return value
        items: list[object] = []
        for item in cast("Sequence[object]", value):
            items.append(
                cast("Mapping[str, object]", item)
                if isinstance(item, Mapping)
                else as_state_route_value_expr(item)
            )
        return items

    @model_validator(mode="after")
    def validate_shape(self) -> StateSpec:
        if self.kind == "set":
            if (
                self.resource is None
                or self.capability_id is None
                or self.field_path is None
                or self.value is None
            ):
                msg = "set state requires resource, capability, field path, and value"
                raise ValueError(msg)
            self._reject("relation", "state")
        elif self.kind == "for_each":
            if self.relation is None or not self.state:
                msg = "for_each state requires relation and state"
                raise ValueError(msg)
            self._reject(
                "resource",
                "capability_id",
                "field_path",
                "value",
                "route_entities",
            )
        return self

    @property
    def field(self) -> str | None:
        if self.capability_id is None or self.field_path is None:
            return None
        return f"{self.capability_id}.{self.field_path}"

    def evaluate(self, *, point_index: int, ctx: EvalContext) -> list[StateRecord]:
        if self.kind == "set":
            resource = _required(self.resource).eval(ctx)
            if not isinstance(resource, str):
                msg = f"state resource must resolve to string, got {resource!r}"
                raise TypeError(msg)
            value = _required(self.value)
            return [
                StateRecord(
                    point_index=point_index,
                    resource=resource,
                    capability_id=_required(self.capability_id),
                    field_path=_required(self.field_path),
                    value=value
                    if isinstance(value, ComputeResultRef)
                    else value.eval(ctx),
                    route_entities=_evaluate_route_entities(self.route_entities, ctx),
                )
            ]
        if self.kind == "for_each":
            records: list[StateRecord] = []
            for row in _required(self.relation).evaluate_in_context(
                EvalContext(params=ctx.params, row={}, outer_row=ctx.row)
            ):
                child_ctx = EvalContext(
                    params=ctx.params,
                    row=row,
                    outer_row=ctx.row,
                )
                for child in _required(self.state):
                    records.extend(
                        child.evaluate(point_index=point_index, ctx=child_ctx)
                    )
            return records
        msg = f"unsupported state spec kind: {self.kind}"
        raise ValueError(msg)

    def _reject(self, *field_names: str) -> None:
        unexpected = [
            field_name
            for field_name in field_names
            if _is_present(getattr(self, field_name))
        ]
        if unexpected:
            msg = f"{self.kind} state cannot contain: {', '.join(unexpected)}"
            raise ValueError(msg)


class StateRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    point_index: int
    resource: str
    capability_id: str = Field(min_length=1)
    field_path: str = Field(min_length=1)
    value: EvaluatedStateValue
    route_entities: list[RouteEntityValue] = Field(default_factory=list)

    @property
    def field(self) -> str:
        return f"{self.capability_id}.{self.field_path}"


class StatePatchRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    point_index: int
    resource: str
    capability_id: str = Field(min_length=1)
    field_path: str = Field(min_length=1)
    before: EvaluatedStateValue | None = None
    after: EvaluatedStateValue

    @property
    def field(self) -> str:
        return f"{self.capability_id}.{self.field_path}"


def validate_state_records(records: list[StateRecord]) -> list[Problem]:
    problems: list[Problem] = []
    seen: dict[
        tuple[int, str, str, str, tuple[str, ...]],
        EvaluatedStateValue,
    ] = {}
    for record in records:
        key = (
            record.point_index,
            record.resource,
            record.capability_id,
            record.field_path,
            _route_entity_key(record.route_entities),
        )
        if key in seen and seen[key] != record.value:
            problems.append(
                compiler_problem(
                    "experiment_conflicting_desired_state",
                    (
                        "conflicting desired state for "
                        f"point={record.point_index} resource={record.resource!r} "
                        f"field={record.field!r}"
                    ),
                    model_location("state", record.point_index),
                    category=ProblemCategory.CONFLICT,
                    details={
                        "point_index": record.point_index,
                        "resource_id": record.resource,
                        "capability_id": record.capability_id,
                        "field_path": record.field_path,
                    },
                )
            )
        seen[key] = record.value
    return problems


def state_patches(records: list[StateRecord]) -> list[StatePatchRecord]:
    patches: list[StatePatchRecord] = []
    previous: dict[
        tuple[str, str, str, tuple[str, ...]],
        EvaluatedStateValue,
    ] = {}
    for record in records:
        key = (
            record.resource,
            record.capability_id,
            record.field_path,
            _route_entity_key(record.route_entities),
        )
        before = previous.get(key)
        if before != record.value:
            patches.append(
                StatePatchRecord(
                    point_index=record.point_index,
                    resource=record.resource,
                    capability_id=record.capability_id,
                    field_path=record.field_path,
                    before=before,
                    after=record.value,
                )
            )
        previous[key] = record.value
    return patches


def _required[T](value: T | None) -> T:
    if value is None:
        raise AssertionError("validated field is unexpectedly missing")
    return value


def as_state_route_value_expr(value: object) -> ScalarOrSeriesValueExpr:
    """Normalize one state-routing entity expression by declared shape."""

    if isinstance(value, ScalarValueExpr | SeriesValueExpr):
        return value
    if isinstance(value, TableValueExpr | RelationExpr):
        msg = "state route entity source must be scalar or series-shaped"
        raise TypeError(msg)
    if isinstance(value, ScalarExpr | SeriesExpr):
        return as_scalar_or_series_value_expr(value)
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return as_scalar_or_series_value_expr(values(cast("Sequence[object]", value)))
    return as_scalar_or_series_value_expr(as_scalar_expr(value))


def _evaluate_route_entities(
    expressions: Sequence[ScalarOrSeriesValueExpr],
    ctx: EvalContext,
) -> list[RouteEntityValue]:
    evaluated: list[CellValue] = []
    for expression in expressions:
        if isinstance(expression, ScalarValueExpr):
            evaluated.append(expression.expr.eval(ctx))
        else:
            series_values = expression.expr.evaluate(ctx)
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
    return not (isinstance(value, list) and not value)


def _route_entity_key(values: list[RouteEntityValue]) -> tuple[str, ...]:
    return tuple(
        value.id if isinstance(value, EntityRef) else value for value in values
    )


StateSpec.model_rebuild()

__all__ = [
    "EvaluatedStateValue",
    "StatePatchRecord",
    "StateRecord",
    "StateSpec",
    "StateSpecKind",
    "StateValueExpr",
    "as_state_route_value_expr",
    "state_patches",
    "validate_state_records",
]
