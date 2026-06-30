from __future__ import annotations

from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, model_validator

from scopecat._planning_diagnostics import planning_diagnostic
from scopecat.models.artifact import ArtifactRef
from scopecat.relations import CellValue, EvalContext, RelationExpr, ScalarExpr

type StateSpecKind = Literal["set", "for_each"]


class StateSpec(BaseModel):
    """Desired-state binding evaluated after point-local parameter patches."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    kind: StateSpecKind
    resource: ScalarExpr | None = None
    field: str | None = None
    value: ScalarExpr | None = None
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
            self._reject("resource", "field", "value")
        return self

    def evaluate(self, *, point_id: int, ctx: EvalContext) -> list[StateRecord]:
        if self.kind == "set":
            resource = _required(self.resource).eval(ctx)
            if not isinstance(resource, str):
                msg = f"state resource must resolve to string, got {resource!r}"
                raise TypeError(msg)
            return [
                StateRecord(
                    point_id=point_id,
                    resource=resource,
                    field=_required(self.field),
                    value=_required(self.value).eval(ctx),
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
                    records.extend(child.evaluate(point_id=point_id, ctx=child_ctx))
            return records
        msg = f"unsupported state spec kind: {self.kind}"
        raise ValueError(msg)

    def _reject(self, *field_names: str) -> None:
        unexpected = [
            field_name
            for field_name in field_names
            if getattr(self, field_name) is not None
        ]
        if unexpected:
            msg = f"{self.kind} state cannot contain: {', '.join(unexpected)}"
            raise ValueError(msg)


class StateRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    point_id: int
    resource: str
    field: str
    value: CellValue


class StatePatchRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    point_id: int
    resource: str
    field: str
    before: CellValue | None = None
    after: CellValue


def validate_state_records(records: list[StateRecord]) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    seen: dict[tuple[int, str, str], CellValue] = {}
    for record in records:
        key = (record.point_id, record.resource, record.field)
        if key in seen and seen[key] != record.value:
            diagnostics.append(
                planning_diagnostic(
                    "error",
                    "experiment_conflicting_desired_state",
                    (
                        "conflicting desired state for "
                        f"point={record.point_id} resource={record.resource!r} "
                        f"field={record.field!r}"
                    ),
                    "state",
                )
            )
        seen[key] = record.value
    return diagnostics


def validate_asset_references(
    *,
    assets: list[ArtifactRef],
    state_records: list[StateRecord],
) -> list[dict[str, Any]]:
    asset_ids = {asset.id for asset in assets}
    referenced_assets = sorted(
        {
            asset_id
            for record in state_records
            for asset_id in _asset_reference_ids(record.value)
        }
    )
    return [
        planning_diagnostic(
            "error",
            "unknown_asset_reference",
            f"expression references unknown experiment asset {asset_id}",
            "assets",
        )
        for asset_id in referenced_assets
        if asset_id not in asset_ids
    ]


def state_patches(records: list[StateRecord]) -> list[StatePatchRecord]:
    patches: list[StatePatchRecord] = []
    previous: dict[tuple[str, str], CellValue] = {}
    for record in records:
        key = (record.resource, record.field)
        before = previous.get(key)
        if before != record.value:
            patches.append(
                StatePatchRecord(
                    point_id=record.point_id,
                    resource=record.resource,
                    field=record.field,
                    before=before,
                    after=record.value,
                )
            )
        previous[key] = record.value
    return patches


def _asset_reference_ids(value: Any) -> set[str]:
    if isinstance(value, dict):
        mapping = cast(dict[object, object], value)
        asset_id = mapping.get("asset_id")
        refs = (
            {asset_id}
            if mapping.get("kind") == "asset" and isinstance(asset_id, str)
            else set()
        )
        for child in mapping.values():
            refs |= _asset_reference_ids(child)
        return refs
    if isinstance(value, list | tuple):
        children = cast(list[object] | tuple[object, ...], value)
        refs: set[str] = set()
        for child in children:
            refs |= _asset_reference_ids(child)
        return refs
    return set()


def _required[T](value: T | None) -> T:
    if value is None:
        raise AssertionError("validated field is unexpectedly missing")
    return value


StateSpec.model_rebuild()
