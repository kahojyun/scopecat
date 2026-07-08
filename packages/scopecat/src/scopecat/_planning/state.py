from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scopecat._planning.diagnostics import planning_diagnostic
from scopecat.relations import CellValue, EvalContext, RelationExpr, ScalarExpr

type StateSpecKind = Literal["set", "for_each"]


class StateSpec(BaseModel):
    """Desired-state binding evaluated after point-local parameter patches."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    kind: StateSpecKind
    resource: ScalarExpr | None = None
    field: str | None = None
    value: ScalarExpr | None = None
    route_entities: list[ScalarExpr] = Field(default_factory=list)
    relation: RelationExpr | None = None
    state: list[StateSpec] | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> StateSpec:
        if self.kind == "set":
            if self.resource is None or self.field is None or self.value is None:
                msg = "set state requires resource, field, and value"
                raise ValueError(msg)
            self._reject("relation", "state")
        elif self.kind == "for_each":
            if self.relation is None or not self.state:
                msg = "for_each state requires relation and state"
                raise ValueError(msg)
            self._reject("resource", "field", "value", "route_entities")
        return self

    def evaluate(self, *, point_index: int, ctx: EvalContext) -> list[StateRecord]:
        if self.kind == "set":
            resource = _required(self.resource).eval(ctx)
            if not isinstance(resource, str):
                msg = f"state resource must resolve to string, got {resource!r}"
                raise TypeError(msg)
            return [
                StateRecord(
                    point_index=point_index,
                    resource=resource,
                    field=_required(self.field),
                    value=_required(self.value).eval(ctx),
                    route_entities=[expr.eval(ctx) for expr in self.route_entities],
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
    field: str
    value: CellValue
    route_entities: list[CellValue] = Field(default_factory=list)


class StatePatchRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    point_index: int
    resource: str
    field: str
    before: CellValue | None = None
    after: CellValue


def validate_state_records(records: list[StateRecord]) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    seen: dict[tuple[int, str, str, tuple[str, ...]], CellValue] = {}
    for record in records:
        key = (
            record.point_index,
            record.resource,
            record.field,
            _route_entity_key(record.route_entities),
        )
        if key in seen and seen[key] != record.value:
            diagnostics.append(
                planning_diagnostic(
                    "error",
                    "experiment_conflicting_desired_state",
                    (
                        "conflicting desired state for "
                        f"point={record.point_index} resource={record.resource!r} "
                        f"field={record.field!r}"
                    ),
                    "state",
                )
            )
        seen[key] = record.value
    return diagnostics


def state_patches(records: list[StateRecord]) -> list[StatePatchRecord]:
    patches: list[StatePatchRecord] = []
    previous: dict[tuple[str, str, tuple[str, ...]], CellValue] = {}
    for record in records:
        key = (record.resource, record.field, _route_entity_key(record.route_entities))
        before = previous.get(key)
        if before != record.value:
            patches.append(
                StatePatchRecord(
                    point_index=record.point_index,
                    resource=record.resource,
                    field=record.field,
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


def _is_present(value: object) -> bool:
    if value is None:
        return False
    return not (isinstance(value, list) and not value)


def _route_entity_key(values: list[CellValue]) -> tuple[str, ...]:
    return tuple(str(value) for value in values)


StateSpec.model_rebuild()
